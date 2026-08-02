"""Comparing runs: regression diff, leaderboard, matrices (PRD F5.2–F5.4).

Everything here is computed from `RunItem` rows plus their non-superseded
attempts and latest scores. Nothing is cached and nothing is stored: a
comparison is a *view* of runs that already happened, so it can never drift
from them.

Three rules the whole module obeys, because every number a user trusts depends
on them:

* **Unscored is not failed.** `verdict` is a tri-state — True, False, or None
  for "nothing resolved". A None never lands in a pass or fail bucket; it gets
  counted and reported on its own. This is D-014 applied to comparisons.
* **Unknown cost is not zero.** If any contributing attempt has no cost, the
  aggregate is flagged `cost_unknown` and the sum covers only what is known.
  A confident $0.00 would be a lie (D-017).
* **Judge spend counts.** Judge calls produce no Attempt row — their usage
  lives in `Score.judge_meta` — so a leaderboard built from attempts alone
  would under-report the cost of exactly the setups that use a judge (D-019).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from sqlmodel import Session, col, select

from gaugix import coverage
from gaugix.domain import AttemptStatus
from gaugix.models.runs import Attempt, Run, RunItem
from gaugix.models.scores import Score


@dataclass(slots=True)
class ItemFacts:
    """One run item flattened into everything a comparison needs."""

    item_id: int
    run_id: int
    set_id: int | None
    set_name: str
    case_id: int | None
    title: str
    executor_key: str
    position: int
    status: str
    verdict: bool | None
    score_value: float | None
    needs_human: bool
    error: str | None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float | None = None
    #: True when some contributing call had no computable cost.
    cost_unknown: bool = False
    latency_ms: int = 0

    @property
    def key(self) -> tuple[int | None, int | None, str]:
        """What makes two items "the same thing" across runs.

        The set is part of the identity, not decoration. One case can belong to
        several sets, so a run covering both produces two legitimately different
        items for it — keying on (case, executor) alone would let one silently
        overwrite the other and the diff would quietly lose a result (D-030).
        """
        return (self.set_id, self.case_id, self.executor_key)


@dataclass(slots=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    cost_unknown: bool = False
    latency_ms: int = 0

    def add(self, facts: ItemFacts) -> None:
        self.prompt_tokens += facts.prompt_tokens
        self.completion_tokens += facts.completion_tokens
        self.latency_ms += facts.latency_ms
        if facts.cost_usd is not None:
            self.cost_usd += facts.cost_usd
        if facts.cost_unknown:
            self.cost_unknown = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "cost_usd": None if self.cost_unknown and self.cost_usd == 0 else self.cost_usd,
            "cost_unknown": self.cost_unknown,
            "latency_ms": self.latency_ms,
        }


# -- loading -------------------------------------------------------------------


def load_item_facts(
    session: Session,
    run_ids: list[int],
    *,
    set_ids: list[int] | None = None,
    executor_keys: list[str] | None = None,
) -> list[ItemFacts]:
    """Every item in these runs, with its usage folded in. One pass per table."""
    if not run_ids:
        return []

    statement = select(RunItem).where(col(RunItem.run_id).in_(run_ids))
    if set_ids:
        statement = statement.where(col(RunItem.set_id).in_(set_ids))
    if executor_keys:
        statement = statement.where(col(RunItem.executor_key).in_(executor_keys))
    items = session.exec(statement).all()
    if not items:
        return []

    item_ids = [item.id for item in items if item.id is not None]
    usage_by_item = _usage_by_item(session, item_ids)

    facts: list[ItemFacts] = []
    for item in items:
        if item.id is None:
            continue
        tokens_in, tokens_out, cost, unknown, latency = usage_by_item.get(
            item.id, (0, 0, 0.0, False, 0)
        )
        facts.append(
            ItemFacts(
                item_id=item.id,
                run_id=item.run_id,
                set_id=item.set_id,
                set_name=item.set_name,
                case_id=item.case_id,
                title=item.case_snapshot.title,
                executor_key=item.executor_key,
                position=item.position,
                status=item.status,
                verdict=item.verdict,
                score_value=item.score_value,
                needs_human=item.needs_human,
                error=item.error,
                prompt_tokens=tokens_in,
                completion_tokens=tokens_out,
                cost_usd=None if (unknown and cost == 0.0) else cost,
                cost_unknown=unknown,
                latency_ms=latency,
            )
        )
    return facts


def _usage_by_item(
    session: Session, item_ids: list[int]
) -> dict[int, tuple[int, int, float, bool, int]]:
    """Tokens, cost and latency per item, from attempts *and* judge scores."""
    totals: dict[int, tuple[int, int, float, bool, int]] = defaultdict(
        lambda: (0, 0, 0.0, False, 0)
    )
    if not item_ids:
        return totals

    attempts = session.exec(
        select(Attempt).where(
            col(Attempt.run_item_id).in_(item_ids), col(Attempt.superseded).is_(False)
        )
    ).all()
    for attempt in attempts:
        tokens_in, tokens_out, cost, unknown, latency = totals[attempt.run_item_id]
        tokens_in += attempt.prompt_tokens
        tokens_out += attempt.completion_tokens
        latency += attempt.latency_ms
        # A failed call still burned tokens, but it has no meaningful price and
        # counting its absence as "unknown" would poison every total.
        if attempt.status != str(AttemptStatus.error):
            if attempt.cost_usd is None:
                unknown = True
            else:
                cost += attempt.cost_usd
        totals[attempt.run_item_id] = (tokens_in, tokens_out, cost, unknown, latency)

    for item_id, usage in _judge_usage(session, item_ids).items():
        tokens_in, tokens_out, cost, unknown, latency = totals[item_id]
        totals[item_id] = (
            tokens_in + usage[0],
            tokens_out + usage[1],
            cost + usage[2],
            unknown or usage[3],
            latency + usage[4],
        )
    return totals


def _judge_usage(
    session: Session, item_ids: list[int]
) -> dict[int, tuple[int, int, float, bool, int]]:
    """Judge spend, taken from the latest Score version per (item, scorer)."""
    rows = session.exec(
        select(Score).where(
            col(Score.run_item_id).in_(item_ids), col(Score.judge_meta_json).is_not(None)
        )
    ).all()

    latest: dict[tuple[int, int], Score] = {}
    for row in rows:
        key = (row.run_item_id, row.scorer_index)
        current = latest.get(key)
        if current is None or row.version > current.version:
            latest[key] = row

    out: dict[int, tuple[int, int, float, bool, int]] = defaultdict(lambda: (0, 0, 0.0, False, 0))
    for row in latest.values():
        usage = (row.judge_meta or {}).get("usage")
        if not isinstance(usage, dict):
            continue
        tokens_in, tokens_out, cost, unknown, latency = out[row.run_item_id]
        raw_cost = usage.get("cost_usd")
        out[row.run_item_id] = (
            tokens_in + int(usage.get("prompt_tokens", 0) or 0),
            tokens_out + int(usage.get("completion_tokens", 0) or 0),
            cost + (float(raw_cost) if raw_cost is not None else 0.0),
            unknown or raw_cost is None,
            latency + int(usage.get("latency_ms", 0) or 0),
        )
    return out


# -- regression diff (PRD F5.3) ------------------------------------------------

#: How one case+executor moved between two runs.
CHANGE_KINDS = ("regressed", "improved", "unchanged", "new", "removed", "unresolved")


@dataclass(slots=True)
class DiffEntry:
    case_id: int | None
    title: str
    set_id: int | None
    set_name: str
    executor_key: str
    kind: str
    baseline_item_id: int | None
    current_item_id: int | None
    baseline_verdict: bool | None
    current_verdict: bool | None
    baseline_status: str | None
    current_status: str | None
    baseline_score: float | None
    current_score: float | None
    score_delta: float | None
    #: Why an entry is `unresolved`, in words, so the UI never has to guess.
    note: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "title": self.title,
            "set_id": self.set_id,
            "set_name": self.set_name,
            "executor_key": self.executor_key,
            "kind": self.kind,
            "baseline_item_id": self.baseline_item_id,
            "current_item_id": self.current_item_id,
            "baseline_verdict": self.baseline_verdict,
            "current_verdict": self.current_verdict,
            "baseline_status": self.baseline_status,
            "current_status": self.current_status,
            "baseline_score": self.baseline_score,
            "current_score": self.current_score,
            "score_delta": self.score_delta,
            "note": self.note,
        }


def _classify(baseline: ItemFacts | None, current: ItemFacts | None) -> tuple[str, str | None]:
    """Which bucket a pair belongs in, and why when it is not obvious."""
    if baseline is None:
        return "new", None
    if current is None:
        return "removed", None

    if baseline.verdict is None or current.verdict is None:
        missing = []
        if baseline.verdict is None:
            missing.append(f"baseline is {_describe(baseline)}")
        if current.verdict is None:
            missing.append(f"current is {_describe(current)}")
        # Never fold "we don't know" into pass or fail — say so instead.
        return "unresolved", "; ".join(missing)

    if baseline.verdict and not current.verdict:
        return "regressed", None
    if not baseline.verdict and current.verdict:
        return "improved", None
    return "unchanged", None


def _describe(facts: ItemFacts) -> str:
    if facts.status == "error":
        return f"errored ({facts.error or 'no detail'})"
    if facts.needs_human:
        return "waiting on human review"
    return f"{facts.status}, unscored"


def _universe_check(
    session: Session, current_run_id: int, baseline_run_id: int, set_ids: list[int] | None
) -> list[dict[str, Any]]:
    """Per set: what each run covered, and whether it was the same cases.

    The paired delta already restricts the arithmetic to shared identities, so
    the numbers are sound. What was missing is the *statement*: a reader seeing
    "40% → 100%" deserves to know the second run was two of those five cases,
    not that the model got better.
    """
    current = session.get(Run, current_run_id)
    baseline = session.get(Run, baseline_run_id)
    if current is None or baseline is None:
        return []

    here = coverage.of_run(current.config)
    there = coverage.of_run(baseline.config)
    wanted = set(set_ids) if set_ids else set(here) | set(there)

    rows: list[dict[str, Any]] = []
    for set_id in sorted(wanted):
        a, b = here.get(set_id), there.get(set_id)
        if a is None and b is None:
            continue
        rows.append(
            {
                "set_id": set_id,
                "set_name": (a or b).set_name,  # type: ignore[union-attr]
                "current": a.describe() if a else "not in this run",
                "baseline": b.describe() if b else "not in the baseline",
                "current_partial": bool(a and a.is_partial),
                "baseline_partial": bool(b and b.is_partial),
                # Empty universes mean a run planned before coverage was
                # recorded; unknown is not the same as mismatched.
                "same_universe": (
                    None
                    if not (a and b and a.universe and b.universe)
                    else a.universe == b.universe
                ),
            }
        )
    return rows


def diff_runs(
    session: Session, current_run_id: int, baseline_run_id: int, *, set_ids: list[int] | None = None
) -> dict[str, Any]:
    """Compare a run against a baseline, case by case and executor by executor."""
    current = load_item_facts(session, [current_run_id], set_ids=set_ids)
    baseline = load_item_facts(session, [baseline_run_id], set_ids=set_ids)
    universes = _universe_check(session, current_run_id, baseline_run_id, set_ids)

    by_key_current = {facts.key: facts for facts in current}
    by_key_baseline = {facts.key: facts for facts in baseline}

    entries: list[DiffEntry] = []
    for key in sorted(
        set(by_key_current) | set(by_key_baseline),
        key=lambda k: (k[2], k[0] if k[0] is not None else -1, k[1] if k[1] is not None else -1),
    ):
        before = by_key_baseline.get(key)
        after = by_key_current.get(key)
        anchor = after or before
        assert anchor is not None  # the key came from one of the two maps
        kind, note = _classify(before, after)
        delta = (
            after.score_value - before.score_value
            if after is not None
            and before is not None
            and after.score_value is not None
            and before.score_value is not None
            else None
        )
        entries.append(
            DiffEntry(
                case_id=anchor.case_id,
                title=anchor.title,
                set_id=anchor.set_id,
                set_name=anchor.set_name,
                executor_key=anchor.executor_key,
                kind=kind,
                baseline_item_id=before.item_id if before else None,
                current_item_id=after.item_id if after else None,
                baseline_verdict=before.verdict if before else None,
                current_verdict=after.verdict if after else None,
                baseline_status=before.status if before else None,
                current_status=after.status if after else None,
                baseline_score=before.score_value if before else None,
                current_score=after.score_value if after else None,
                score_delta=delta,
                note=note,
            )
        )

    counts = dict.fromkeys(CHANGE_KINDS, 0)
    for entry in entries:
        counts[entry.kind] += 1

    current_executors = sorted({facts.executor_key for facts in current})
    baseline_executors = sorted({facts.executor_key for facts in baseline})
    both_executors = sorted(set(current_executors) & set(baseline_executors))

    # The only fair headline. Both runs restricted to the identities they share,
    # so the delta answers "did the same work get better or worse" instead of
    # "were these two runs about the same things" (D-031).
    shared = set(by_key_current) & set(by_key_baseline)
    paired_current = [by_key_current[k] for k in shared]
    paired_baseline = [by_key_baseline[k] for k in shared]

    return {
        "current_run_id": current_run_id,
        "baseline_run_id": baseline_run_id,
        "counts": counts,
        "entries": [entry.as_dict() for entry in entries],
        # When the two runs used different executors, every case on the odd
        # executor shows as new/removed. Saying so up front stops that reading
        # as a catastrophic regression.
        "executors": {
            "both": both_executors,
            "only_current": sorted(set(current_executors) - set(baseline_executors)),
            "only_baseline": sorted(set(baseline_executors) - set(current_executors)),
        },
        # Which sets the two runs covered the same *cases* of. Distinct from
        # the API's `coverage`, which is about which baseline each set points
        # at. Two full runs of one set are only like-for-like if the set did
        # not change between them, and "both were full" does not show that.
        "case_universes": universes,
        # False when the two runs share no (set, case, executor) at all. The UI
        # must then refuse to draw an overall delta: there is no pair of numbers
        # here that means anything.
        "comparable": bool(shared),
        "paired": {
            "items": len(shared),
            "pass_rate": {
                "current": pass_rate(paired_current),
                "baseline": pass_rate(paired_baseline),
            },
            "mean_score": {
                "current": mean_score(paired_current),
                "baseline": mean_score(paired_baseline),
            },
        },
        # Kept for context, and explicitly *not* the headline: each side covers
        # whatever that run happened to contain, which need not be the same work.
        "pass_rate": {
            "current": pass_rate(current),
            "baseline": pass_rate(baseline),
        },
        "mean_score": {
            "current": mean_score(current),
            "baseline": mean_score(baseline),
        },
    }


# -- shared metrics ------------------------------------------------------------


def pass_rate(facts: list[ItemFacts]) -> float | None:
    """Passed ÷ scored. None when nothing was scored — not 0%, which reads as failure."""
    scored = [f for f in facts if f.verdict is not None]
    if not scored:
        return None
    return round(100 * sum(1 for f in scored if f.verdict) / len(scored), 1)


def mean_score(facts: list[ItemFacts]) -> float | None:
    values = [f.score_value for f in facts if f.score_value is not None]
    if not values:
        return None
    return round(sum(values) / len(values), 1)


def _bucket_stats(facts: list[ItemFacts]) -> dict[str, Any]:
    usage = Usage()
    for item in facts:
        usage.add(item)
    scored = [f for f in facts if f.verdict is not None]
    return {
        "items": len(facts),
        "scored": len(scored),
        "passed": sum(1 for f in scored if f.verdict),
        "failed": sum(1 for f in scored if not f.verdict),
        "unscored": len(facts) - len(scored),
        "errors": sum(1 for f in facts if f.status == "error"),
        "needs_human": sum(1 for f in facts if f.needs_human),
        "pass_rate": pass_rate(facts),
        "mean_score": mean_score(facts),
        "mean_latency_ms": round(usage.latency_ms / len(facts)) if facts else None,
        **usage.as_dict(),
    }


# -- leaderboard (PRD F5.4) ----------------------------------------------------


def leaderboard(
    session: Session,
    run_ids: list[int],
    *,
    set_ids: list[int] | None = None,
    executor_keys: list[str] | None = None,
) -> dict[str, Any]:
    """Executors ranked by pass rate, with the cost and latency they charged for it."""
    facts = load_item_facts(session, run_ids, set_ids=set_ids, executor_keys=executor_keys)

    by_executor: dict[str, list[ItemFacts]] = defaultdict(list)
    for item in facts:
        by_executor[item.executor_key].append(item)

    rows = [
        {"executor_key": executor, **_bucket_stats(items)}
        for executor, items in by_executor.items()
    ]
    # Rank on pass rate, then mean score, then cheaper wins. An executor with
    # nothing scored has no rank to claim, so it sorts last rather than first.
    rows.sort(
        key=lambda r: (
            r["pass_rate"] is not None,
            r["pass_rate"] or 0,
            r["mean_score"] or 0,
            -(r["cost_usd"] or 0),
        ),
        reverse=True,
    )
    for position, row in enumerate(rows, start=1):
        row["rank"] = position if row["pass_rate"] is not None else None

    return {
        "run_ids": run_ids,
        "rows": rows,
        "totals": _bucket_stats(facts),
    }


# -- matrices (PRD F5.2) -------------------------------------------------------


def matrix(
    session: Session,
    run_ids: list[int],
    *,
    set_ids: list[int] | None = None,
    executor_keys: list[str] | None = None,
) -> dict[str, Any]:
    """Rows = cases (grouped by set), columns = executors, cells = verdict + score."""
    facts = load_item_facts(session, run_ids, set_ids=set_ids, executor_keys=executor_keys)
    executors = sorted({item.executor_key for item in facts})

    rows: dict[tuple[int | None, int | None], dict[str, Any]] = {}
    for item in facts:
        row_key = (item.set_id, item.case_id)
        row = rows.setdefault(
            row_key,
            {
                "set_id": item.set_id,
                "set_name": item.set_name,
                "case_id": item.case_id,
                "title": item.title,
                "position": item.position,
                "cells": {},
            },
        )
        # With several runs selected, the newest item for a cell wins — a rerun
        # is meant to replace what it reran, not to appear beside it.
        existing = row["cells"].get(item.executor_key)
        if existing is None or item.item_id > existing["item_id"]:
            row["cells"][item.executor_key] = {
                "item_id": item.item_id,
                "run_id": item.run_id,
                "status": item.status,
                "verdict": item.verdict,
                "score_value": item.score_value,
                "needs_human": item.needs_human,
                "error": item.error,
            }

    ordered = sorted(rows.values(), key=lambda r: (r["set_name"], r["position"], r["title"]))
    return {"executors": executors, "rows": ordered}


def aggregate_matrix(
    session: Session,
    run_ids: list[int],
    *,
    set_ids: list[int] | None = None,
    executor_keys: list[str] | None = None,
) -> dict[str, Any]:
    """Rows = sets, columns = executors, cells = pass rate / mean score / cost."""
    facts = load_item_facts(session, run_ids, set_ids=set_ids, executor_keys=executor_keys)
    executors = sorted({item.executor_key for item in facts})

    grouped: dict[tuple[int | None, str], list[ItemFacts]] = defaultdict(list)
    names: dict[int | None, str] = {}
    for item in facts:
        grouped[(item.set_id, item.executor_key)].append(item)
        names[item.set_id] = item.set_name

    rows = []
    for set_id in sorted(names, key=lambda s: names[s]):
        cells = {
            executor: _bucket_stats(grouped[(set_id, executor)])
            for executor in executors
            if grouped.get((set_id, executor))
        }
        set_items = [f for f in facts if f.set_id == set_id]
        rows.append(
            {
                "set_id": set_id,
                "set_name": names[set_id],
                "cells": cells,
                "totals": _bucket_stats(set_items),
            }
        )

    return {"executors": executors, "rows": rows, "totals": _bucket_stats(facts)}


# -- per-set history (PRD F5.1) ------------------------------------------------


def set_trends(
    session: Session, *, limit_runs: int = 10, include_partial: bool = False
) -> list[dict[str, Any]]:
    """Pass rate per set across recent runs, each set's points oldest first.

    Computed per set, never run-wide. A run covering three sets has three
    different pass rates; plotting the run's overall rate on all three lines
    lets one set's regression show up in another set's history, and lets a
    healthy set inherit a sick one's dip (D-032).

    Partial runs are excluded by default. A run over two of a set's five cases
    produces a number in exactly the same shape as a full-set number, and a
    trend line that mixes them is a line about nothing — 100% over two cases
    sitting where 40% over five belongs (D-053). The excluded count travels
    with each series so the dashboard can say they were left out rather than
    quietly showing a shorter line.
    """
    run_ids_with_items = set(session.exec(select(RunItem.run_id).distinct()).all())
    runs = [r for r in session.exec(select(Run)).all() if r.id in run_ids_with_items]
    runs.sort(key=lambda r: (r.created_at, r.id or 0), reverse=True)

    recent = runs[: max(1, limit_runs)]
    by_id = {r.id: r for r in recent if r.id is not None}
    if not by_id:
        return []

    rows = session.exec(
        select(RunItem.run_id, RunItem.set_id, RunItem.set_name, RunItem.verdict).where(
            col(RunItem.run_id).in_(list(by_id))
        )
    ).all()

    #: (run, set) -> scored, passed, name. Unscored items never enter either count.
    tally: dict[tuple[int, int], tuple[int, int, str]] = {}
    for run_id, set_id, set_name, verdict in rows:
        if set_id is None or verdict is None:
            continue
        scored, passed, name = tally.get((run_id, set_id), (0, 0, set_name))
        tally[(run_id, set_id)] = (scored + 1, passed + (1 if verdict else 0), name)

    series: dict[int, dict[str, Any]] = {}
    for (run_id, set_id), (scored, passed, set_name) in tally.items():
        run = by_id[run_id]
        cover = coverage.of_run(run.config).get(set_id)
        partial = cover.is_partial if cover else False
        entry = series.setdefault(
            set_id,
            {
                "set_id": set_id,
                "set_name": set_name,
                "points": [],
                "partial_runs_excluded": 0,
            },
        )
        if partial and not include_partial:
            entry["partial_runs_excluded"] += 1
            continue
        entry["points"].append(
            {
                "run_id": run_id,
                "run_name": run.name,
                "created_at": run.created_at,
                "scored": scored,
                "passed": passed,
                "pass_rate": round(100 * passed / scored, 1),
                "partial": partial,
                "coverage": cover.describe() if cover else "",
            }
        )

    for entry in series.values():
        entry["points"].sort(key=lambda p: (p["created_at"], p["run_id"]))
    return sorted(series.values(), key=lambda e: str(e["set_name"]))


# -- baseline lookup -----------------------------------------------------------


def baseline_run_for(session: Session, set_id: int, *, exclude_run_id: int | None = None) -> int:
    """The run currently marked baseline for a set, or 0 when there is none."""
    return baselines_for_sets(session, [set_id], exclude_run_id=exclude_run_id).get(set_id, 0)


def baselines_for_sets(
    session: Session, set_ids: list[int], *, exclude_run_id: int | None = None
) -> dict[int, int]:
    """Each set's blessed baseline run, resolved *per set* rather than run-wide.

    A run can cover several sets, and each set blesses its own baseline. Taking
    the first baseline found and applying it to every set is how one set's
    history ends up being compared against another set's — the numbers look
    plausible and mean nothing (D-029).
    """
    if not set_ids:
        return {}
    wanted = set(set_ids)
    found: dict[int, int] = {}
    for run in session.exec(select(Run)).all():
        if run.id is None or run.id == exclude_run_id:
            continue
        for set_id in run.is_baseline_for:
            # Ties cannot normally happen — blessing a run un-blesses the last —
            # but if the data ever says otherwise, the newest run wins.
            if set_id in wanted and run.id > found.get(set_id, 0):
                found[set_id] = run.id
    return found


@dataclass(slots=True)
class BaselineGroup:
    """Sets that share one baseline run — the unit a single diff can honestly cover."""

    baseline_run_id: int
    set_ids: list[int]


def group_sets_by_baseline(baselines: dict[int, int]) -> list[BaselineGroup]:
    """Bucket sets by the baseline they point at, widest bucket first.

    A diff spanning two baselines is not one comparison, it is two. Grouping is
    what lets the API scope a diff to a coherent slice and name the rest.
    """
    buckets: dict[int, list[int]] = defaultdict(list)
    for set_id, run_id in baselines.items():
        if run_id:
            buckets[run_id].append(set_id)
    groups = [
        BaselineGroup(baseline_run_id=run_id, set_ids=sorted(sets))
        for run_id, sets in buckets.items()
    ]
    groups.sort(key=lambda g: (-len(g.set_ids), g.set_ids[0]))
    return groups
