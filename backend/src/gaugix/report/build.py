"""Building a self-contained HTML report (PRD F5.5).

The contract is strict and worth stating plainly: **one file, no network.** The
export must open years from now on a laptop with no internet, so there is no
CDN, no web font, no external stylesheet and no remote image anywhere in the
output. `tests/api/test_report.py` asserts that mechanically.

The second contract is editorial: *pretty for style, fair for content*. The
stylesheet can be as polished as we like; the numbers are the ones the run
actually produced. Nothing is rounded to flatter, no failure is folded away,
and the methodology footer names every model, harness, scorer and judge that
touched the result — because a report you cannot audit is marketing.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlmodel import Session, col, func, select

from gaugix import __version__, coverage
from gaugix.compare import (
    ItemFacts,
    aggregate_matrix,
    diff_runs,
    leaderboard,
    load_item_facts,
    mean_score,
    pass_rate,
)
from gaugix.config import redact_for_display
from gaugix.models.runs import Attempt, Run, RunItem
from gaugix.models.scores import Score
from gaugix.report import svg

TEMPLATE_DIR = Path(__file__).parent / "templates"


def _environment() -> Environment:
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["money"] = _money
    env.filters["pct"] = _pct
    env.filters["num"] = _num
    env.filters["pretty"] = _pretty
    return env


def _money(value: float | None) -> str:
    if value is None:
        return "n/a"
    if value == 0:
        return "$0.00"
    return f"${value:.4f}" if value < 0.01 else f"${value:.2f}"


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value:g}%"


def _num(value: float | None) -> str:
    return "—" if value is None else f"{value:,.0f}"


def _pretty(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")


def _scorer_summary(facts: list[ItemFacts], session: Session, run_ids: list[int]) -> list[str]:
    """Which scorer types actually decided these verdicts, for the methodology note."""
    items = session.exec(select(RunItem).where(col(RunItem.run_id).in_(run_ids))).all()
    kinds: set[str] = set()
    for item in items:
        for scorer in item.case_snapshot.scoring:
            kinds.add(str(scorer.type))
    return sorted(kinds)


def _judge_note(session: Session) -> str:
    """Name the judge, or say plainly that models graded themselves."""
    from gaugix.api.settings import KEY_DEFAULT_JUDGE_EXECUTOR, read_setting
    from gaugix.models.executors import Executor

    executor_id = read_setting(session, KEY_DEFAULT_JUDGE_EXECUTOR, None)
    if executor_id is None:
        return (
            "No default judge was configured, so any llm_judge scorer graded with the "
            "same executor it was evaluating — a model scoring its own output."
        )
    executor = session.get(Executor, int(executor_id))
    return f"llm_judge scorers graded with {executor.name}." if executor else ""


def _run_context(session: Session, run: Run) -> dict[str, Any]:
    run_id = run.id or 0
    facts = load_item_facts(session, [run_id])
    board = leaderboard(session, [run_id])
    duration = None
    if run.started_at and run.finished_at:
        duration = (run.finished_at - run.started_at).total_seconds()

    failed_facts = [f for f in facts if f.verdict is False or f.status == "error"]
    failures = _failure_details(session, failed_facts, [run])
    return {
        "run": run,
        "facts": facts,
        "leaderboard": board,
        "totals": board["totals"],
        "duration_s": duration,
        "failures": failures,
        "failure_count": len(failed_facts),
        "charts": {
            "pass_rate": svg.bar_chart(
                [(row["executor_key"], row["pass_rate"]) for row in board["rows"]],
                title="Pass rate by executor",
            ),
            "split": svg.stacked_bar(
                board["totals"]["passed"],
                board["totals"]["failed"],
                board["totals"]["unscored"],
            ),
        },
    }


def _failure_details(
    session: Session,
    facts: list[ItemFacts],
    runs: list[Run],
) -> list[dict[str, Any]]:
    """Make exported failures independently explainable and reproducible."""
    ordered = sorted(
        facts,
        key=lambda fact: (fact.set_name, fact.executor_key, fact.position),
    )[:200]
    item_ids = [fact.item_id for fact in ordered]
    if not item_ids:
        return []
    items = {
        item.id: item
        for item in session.exec(select(RunItem).where(col(RunItem.id).in_(item_ids))).all()
        if item.id is not None
    }
    attempts: dict[int, Attempt] = {}
    for attempt_row in session.exec(
        select(Attempt)
        .where(
            col(Attempt.run_item_id).in_(item_ids),
            col(Attempt.superseded).is_(False),
        )
        .order_by(col(Attempt.run_item_id), col(Attempt.n))
    ).all():
        attempts[attempt_row.run_item_id] = attempt_row
    latest_scores: dict[tuple[int, int], Score] = {}
    for score in session.exec(
        select(Score)
        .where(col(Score.run_item_id).in_(item_ids))
        .order_by(col(Score.run_item_id), col(Score.scorer_index), col(Score.version))
    ).all():
        latest_scores[(score.run_item_id, score.scorer_index)] = score
    executors = {
        (run.id or 0, snapshot.key): redact_for_display(snapshot.model_dump(mode="json"))
        for run in runs
        for snapshot in run.executors
    }

    details: list[dict[str, Any]] = []
    for fact in ordered:
        item = items.get(fact.item_id)
        if item is None:
            continue
        snapshot = item.case_snapshot
        attempt = attempts.get(fact.item_id)
        scores = [
            score
            for (score_item_id, _index), score in latest_scores.items()
            if score_item_id == fact.item_id
        ]
        scores.sort(key=lambda score: score.scorer_index)
        score_details = []
        for score in scores:
            spec = (
                snapshot.scoring[score.scorer_index]
                if score.scorer_index < len(snapshot.scoring)
                else None
            )
            score_details.append(
                {
                    "type": score.scorer_type,
                    "required": spec.required if spec is not None else None,
                    "passed": score.passed,
                    "rationale": redact_for_display(score.rationale),
                }
            )
        details.append(
            {
                "run_id": fact.run_id,
                "status": fact.status,
                "title": redact_for_display(fact.title),
                "set_name": fact.set_name,
                "executor_key": fact.executor_key,
                "error": redact_for_display(fact.error),
                "input": redact_for_display(
                    [message.model_dump(mode="json") for message in snapshot.input]
                ),
                "reference": redact_for_display(snapshot.reference),
                "actual": (redact_for_display(attempt.output_text) if attempt is not None else ""),
                "attempt_error": (
                    redact_for_display(attempt.error) if attempt is not None else None
                ),
                "score_details": score_details,
                "scoring": redact_for_display(
                    [spec.model_dump(mode="json") for spec in snapshot.scoring]
                ),
                "case_tags": redact_for_display(snapshot.tags),
                "case_notes": redact_for_display(snapshot.notes),
                "executor": executors.get((fact.run_id, fact.executor_key)),
                "provider_messages": (
                    redact_for_display(attempt.messages or []) if attempt is not None else []
                ),
                "invocation_metadata": (
                    redact_for_display(attempt.request or {}) if attempt is not None else {}
                ),
            }
        )
    return details


def _datasets(run: Run) -> list[dict[str, Any]]:
    """Benchmark provenance frozen into this run, one row per installed set.

    Only sets installed from the catalogue have any; a hand-written set has
    nothing to cite and contributes no row rather than an empty one.
    """
    rows: list[dict[str, Any]] = []
    for entry in run.config.get("sets", []):
        record = entry.get("provenance") if isinstance(entry, dict) else None
        if not isinstance(record, dict) or not record.get("benchmark"):
            continue
        # A set edited since install is a derived set. It cannot carry the
        # original's comparability claim into a report, whatever the catalogue
        # said when it was installed (D-062).
        modified = bool(record.get("modified"))
        rows.append(
            {
                "set_name": entry.get("name") or record.get("benchmark_name"),
                "benchmark": record.get("benchmark_name") or record.get("benchmark"),
                "revision": record.get("source_revision"),
                "sha256": record.get("source_sha256"),
                "licence": record.get("licence"),
                "fidelity": "derived from " + str(record.get("method_fidelity"))
                if modified
                else record.get("method_fidelity"),
                "method_version": record.get("method_version"),
                "comparable": False if modified else record.get("comparable_to_published"),
                "modified": modified,
                "modified_reasons": list(record.get("modified_reasons") or []),
                # Installed before Gaugix recorded provenance: the benchmark is
                # known from the tags, the revision and method behind the number
                # are not. Saying so is the honest row; the alternative was no
                # row at all, which read as "hand-written set" (D-066).
                "legacy": bool(record.get("legacy")),
                "installed_at": record.get("installed_at"),
                "scope": record.get("scope"),
                "sample_seed": record.get("sample_seed"),
            }
        )
    return rows


def build_run_report(session: Session, run: Run) -> str:
    """One run: headline metrics, charts, the failures, and how it was measured."""
    context = _run_context(session, run)
    run_id = run.id or 0
    context.update(
        {
            "kind": "run",
            "title": run.name or f"Run {run_id}",
            # A report is read away from the app, so a partial run has to
            # declare itself above the numbers rather than rely on context
            # the reader does not have (D-053).
            "partial_coverage": [
                f"{c.set_name}: {c.describe()}" for c in coverage.partial_sets(run.config)
            ],
            # Which dataset, at which revision, scored by which method version.
            # Without it "we ran IFEval in August" is unprovable from the file.
            "datasets": _datasets(run),
            "generated_at": _stamp(),
            "version": __version__,
            "executors": run.executors,
            "scorer_kinds": _scorer_summary(context["facts"], session, [run_id]),
            "judge_note": _judge_note(session),
            "aggregate": aggregate_matrix(session, [run_id]),
            "attempt_count": _attempt_count(session, [run_id]),
        }
    )
    return _environment().get_template("report.html").render(**context)


def build_comparison_report(
    session: Session, run_ids: list[int], *, baseline_run_id: int | None = None
) -> str:
    """Several runs side by side, plus the regression diff when a baseline is named."""
    runs = [
        run for run in session.exec(select(Run)).all() if run.id is not None and run.id in run_ids
    ]
    runs.sort(key=lambda r: run_ids.index(r.id or 0))
    facts = load_item_facts(session, run_ids)
    board = leaderboard(session, run_ids)
    failed_facts = [f for f in facts if f.verdict is False or f.status == "error"]
    failures = _failure_details(session, failed_facts, runs)

    diff = None
    delta_rows: list[tuple[str, float]] = []
    if baseline_run_id is not None and run_ids:
        current_id = next((r for r in run_ids if r != baseline_run_id), run_ids[0])
        safe_diff = redact_for_display(diff_runs(session, current_id, baseline_run_id))
        if not isinstance(safe_diff, dict):
            raise TypeError("redacted comparison diff must remain an object")
        diff = safe_diff
        delta_rows = [
            (entry["title"], entry["score_delta"])
            for entry in diff["entries"]
            if entry["score_delta"]
        ][:12]

    return (
        _environment()
        .get_template("report.html")
        .render(
            kind="comparison",
            title=f"Comparison of {len(runs)} {'run' if len(runs) == 1 else 'runs'}",
            # Any partial run in the comparison taints the headline, so all of
            # them are named — with the run they came from, since a comparison
            # report holds several.
            partial_coverage=[
                f"{run.name} — {c.set_name}: {c.describe()}"
                for run in runs
                for c in coverage.partial_sets(run.config)
            ],
            generated_at=_stamp(),
            version=__version__,
            runs=runs,
            facts=facts,
            leaderboard=board,
            totals=board["totals"],
            aggregate=aggregate_matrix(session, run_ids),
            diff=diff,
            executors=[snap for run in runs for snap in run.executors],
            scorer_kinds=_scorer_summary(facts, session, run_ids),
            judge_note=_judge_note(session),
            attempt_count=_attempt_count(session, run_ids),
            pass_rate_overall=pass_rate(facts),
            mean_score_overall=mean_score(facts),
            failures=failures,
            failure_count=len(failed_facts),
            charts={
                "pass_rate": svg.bar_chart(
                    [(row["executor_key"], row["pass_rate"]) for row in board["rows"]],
                    title="Pass rate by executor",
                ),
                "split": svg.stacked_bar(
                    board["totals"]["passed"],
                    board["totals"]["failed"],
                    board["totals"]["unscored"],
                ),
                "deltas": svg.delta_chart(delta_rows) if delta_rows else "",
            },
        )
    )


def _attempt_count(session: Session, run_ids: list[int]) -> int:
    return int(
        session.exec(
            select(func.count())
            .select_from(Attempt)
            .join(RunItem, col(RunItem.id) == col(Attempt.run_item_id))
            .where(col(RunItem.run_id).in_(run_ids))
        ).one()
    )
