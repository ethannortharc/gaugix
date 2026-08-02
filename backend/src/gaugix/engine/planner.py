"""Run planner: expand {sets} × {executors} into persisted run items.

The planner is where **fairness** is established (ARCHITECTURE §3, "Snapshot
rules"). At plan time it freezes:

* the full case content *and its resolved scoring config* into each run item, and
* every executor's model params into the run config.

After that, editing a case or an executor cannot change what a past run means.
Everything is written in one transaction **before** execution starts, so a crash
between planning and running leaves a resumable `pending` run rather than a
half-built one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlmodel import Session, col, select

from gaugix import coverage
from gaugix.domain import ExecutorSnapshot, ItemStatus, RunStatus, ScorerSpec, ScorerType
from gaugix.errors import NotFoundError, ValidationError
from gaugix.models.cases import EvalCase, EvalSet, SetMembership
from gaugix.models.executors import Executor, HarnessProfile, ModelProfile
from gaugix.models.runs import Run, RunItem
from gaugix.scoring.judge_config import resolve_judge_executor


@dataclass(slots=True)
class PlanRequest:
    set_ids: list[int]
    executor_ids: list[int]
    name: str | None = None
    concurrency: int = 4
    auto_score: bool = True
    parent_run_id: int | None = None
    #: Restrict the run to these cases. `None` means the whole of every chosen
    #: set; a list means "only these, wherever they appear in the selection".
    case_ids: list[int] | None = None


@dataclass(slots=True)
class PlannedRun:
    run: Run
    item_count: int


def resolve_scoring(case: EvalCase, eval_set: EvalSet) -> list[ScorerSpec]:
    """A case's own scorers, or the set default when it has none (PRD F4.2)."""
    return case.scoring if case.scoring else eval_set.default_scoring


def load_executor_snapshots(session: Session, executor_ids: list[int]) -> list[ExecutorSnapshot]:
    """Freeze each executor with its model and harness config."""
    snapshots: list[ExecutorSnapshot] = []
    for executor_id in executor_ids:
        executor = session.get(Executor, executor_id)
        if executor is None:
            raise NotFoundError(f"Executor {executor_id} does not exist")
        model = session.get(ModelProfile, executor.model_profile_id)
        harness = session.get(HarnessProfile, executor.harness_profile_id)
        if model is None or harness is None:
            raise ValidationError(
                f"Executor {executor.name!r} is missing its model or harness profile"
            )
        snapshots.append(executor.to_snapshot(model, harness))

    keys = [s.key for s in snapshots]
    if len(set(keys)) != len(keys):
        raise ValidationError("executors must be distinct", details={"keys": keys})
    return snapshots


def suggest_name(
    set_names: list[str], executor_keys: list[str], *, case_count: int | None = None
) -> str:
    """A run name a human can recognise in a list a month later.

    `case_count` is passed only for a partial run, where the set's name alone
    would be a lie: "Regressions × gpt-4o" reads as the whole set even when it
    covered nine of its four hundred cases.
    """
    sets_part = set_names[0] if len(set_names) == 1 else f"{len(set_names)} sets"
    exec_part = executor_keys[0] if len(executor_keys) == 1 else f"{len(executor_keys)} executors"
    if case_count is not None:
        sets_part = f"{sets_part} ({case_count} cases)"
    return f"{sets_part} × {exec_part}"


def preview(
    session: Session,
    set_ids: list[int],
    executor_ids: list[int],
    case_ids: list[int] | None = None,
) -> dict[str, Any]:
    """Matrix preview for the run builder: counts and per-set breakdown (PRD F3.1)."""
    sets = _load_sets(session, set_ids)
    executors = load_executor_snapshots(session, executor_ids)

    per_set = []
    total_cases = 0
    total_available = 0
    for eval_set in sets:
        cases = _cases_in_set(session, eval_set.id or 0, case_ids)
        available = (
            len(cases) if case_ids is None else len(_cases_in_set(session, eval_set.id or 0))
        )
        total_cases += len(cases)
        total_available += available
        per_set.append(
            {
                "set_id": eval_set.id,
                "name": eval_set.name,
                "case_count": len(cases),
                "available_case_count": available,
            }
        )

    return {
        "sets": per_set,
        "executors": [{"key": e.key, "provider": str(e.model.provider)} for e in executors],
        "case_count": total_cases,
        "available_case_count": total_available,
        "executor_count": len(executors),
        "item_count": total_cases * len(executors),
        "suggested_name": suggest_name(
            [s.name for s in sets],
            [e.key for e in executors],
            case_count=total_cases if case_ids is not None else None,
        ),
    }


def plan_run(session: Session, request: PlanRequest) -> PlannedRun:
    """Create the run and all its items in one transaction. Nothing executes yet."""
    if not request.set_ids:
        raise ValidationError("choose at least one eval set")
    if not request.executor_ids:
        raise ValidationError("choose at least one executor")

    sets = _load_sets(session, request.set_ids)
    executors = load_executor_snapshots(session, request.executor_ids)
    case_ids = request.case_ids

    planned_cases = {
        eval_set.id: _cases_in_set(session, eval_set.id or 0, case_ids) for eval_set in sets
    }
    selected = sum(len(v) for v in planned_cases.values())

    run = Run(
        name=request.name
        or suggest_name(
            [s.name for s in sets],
            [e.key for e in executors],
            case_count=selected if case_ids is not None else None,
        ),
        status=str(RunStatus.pending),
        parent_run_id=request.parent_run_id,
    )
    run.config = {
        "executors": [e.model_dump(mode="json") for e in executors],
        # A judge is part of the measurement instrument just as much as the
        # subject executor is. Freeze every resolved non-self judge so changing
        # Settings or editing that executor during a long run cannot switch the
        # grader halfway through. The scorer hash ties the snapshot to the
        # exact rubric/scale/config frozen on each item.
        "judge_executors": _freeze_judge_executors(session, sets, planned_cases),
        # Each set carries what this run covered of it and what it held at the
        # time. Recomputing "available" later would restate what the run
        # measured every time the set changed (D-053).
        "sets": [
            {
                **coverage.freeze(
                    set_id=s.id or 0,
                    set_name=s.name,
                    selected=[c.id or 0 for c in planned_cases[s.id]],
                    available=len(_cases_in_set(session, s.id or 0)),
                ),
                # The dataset this ran against, frozen with everything else the
                # run freezes — *including* whether it had already drifted from
                # what was installed. Freezing only the install record let a set
                # someone had edited produce a report still claiming the
                # original benchmark and its comparability (D-062).
                #
                # Via the same helper the API reads, so a set installed before
                # provenance existed freezes its legacy record instead of
                # nothing at all and produces a report that can name its
                # dataset (D-066).
                **_provenance(session, s),
            }
            for s in sets
        ],
        "concurrency": max(1, request.concurrency),
        "auto_score": request.auto_score,
        # Recorded so a rerun covers the same cases, and so the run page can say
        # "part of this set" rather than implying the whole of it. Absent on
        # whole-set runs, which keeps existing configs byte-identical.
        **({"case_ids": sorted(case_ids)} if case_ids is not None else {}),
    }
    run.totals = empty_totals()
    session.add(run)
    session.flush()

    # One lane per executor; within a lane, set order then case position.
    position = 0
    item_count = 0
    for executor in executors:
        position = 0
        for eval_set in sets:
            for case in planned_cases[eval_set.id]:
                item = RunItem(
                    run_id=run.id or 0,
                    set_id=eval_set.id,
                    set_name=eval_set.name,
                    case_id=case.id,
                    executor_key=executor.key,
                    position=position,
                    status=str(ItemStatus.pending),
                )
                item.case_snapshot = case.to_snapshot(resolve_scoring(case, eval_set))
                session.add(item)
                position += 1
                item_count += 1

    if item_count == 0:
        raise ValidationError(
            "none of the chosen cases are in the chosen sets"
            if case_ids is not None
            else "the chosen sets contain no cases"
        )

    run.totals = {**empty_totals(), "items": item_count, "pending": item_count}
    session.add(run)
    session.commit()
    session.refresh(run)
    return PlannedRun(run=run, item_count=item_count)


def _freeze_judge_executors(
    session: Session,
    sets: list[EvalSet],
    planned_cases: dict[int | None, list[EvalCase]],
) -> dict[str, dict[str, Any]]:
    """Resolved judge choice keyed by each frozen scorer configuration.

    `self` is a choice too. Recording it explicitly prevents a default judge
    added after planning from changing an already-planned run. An error should
    normally have been blocked by preflight; freezing it keeps direct planner
    callers fail-closed instead of making their outcome timing-dependent.
    """
    frozen: dict[str, dict[str, Any]] = {}
    for eval_set in sets:
        for case in planned_cases[eval_set.id]:
            for spec in resolve_scoring(case, eval_set):
                if spec.type != ScorerType.llm_judge:
                    continue
                key = spec.config_hash()
                if key in frozen:
                    continue
                resolution = resolve_judge_executor(session, dict(spec.params))
                if resolution.error is not None:
                    frozen[key] = {"mode": "error", "error": resolution.error}
                elif resolution.executor is None:
                    frozen[key] = {"mode": "self"}
                else:
                    frozen[key] = {
                        "mode": "executor",
                        "executor": resolution.executor.model_dump(mode="json"),
                    }
    return frozen


def empty_totals() -> dict[str, Any]:
    return {
        "items": 0,
        "pending": 0,
        "invoking": 0,
        "scoring": 0,
        "passed": 0,
        "failed": 0,
        "error": 0,
        "skipped": 0,
        "needs_human": 0,
        # Verdicts are tracked apart from statuses: an item can finish fine with
        # no verdict at all (no scorers), and counting that as a pass would
        # overstate the pass rate.
        "scored": 0,
        "verdict_passed": 0,
        "unscored": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "cost_usd": 0.0,
        "judge_cost_usd": 0.0,
        "cost_unknown": False,
    }


def _provenance(session: Session, eval_set: EvalSet) -> dict[str, Any]:
    """The frozen `provenance` entry for one set, or nothing for a hand-made one.

    Imported here rather than at module scope: `benchmarks` imports the case
    models, and the planner is imported by them.
    """
    from gaugix.benchmarks import effective_provenance

    record = effective_provenance(session, eval_set)
    return {"provenance": record} if record else {}


def _load_sets(session: Session, set_ids: list[int]) -> list[EvalSet]:
    sets: list[EvalSet] = []
    for set_id in set_ids:
        eval_set = session.get(EvalSet, set_id)
        if eval_set is None:
            raise NotFoundError(f"Set {set_id} does not exist")
        sets.append(eval_set)
    return sets


def _cases_in_set(
    session: Session, set_id: int, case_ids: list[int] | None = None
) -> list[EvalCase]:
    """Live cases in membership order — trashed cases are never planned into a run.

    `case_ids` narrows the set to a chosen subset. It filters rather than
    selects: an id that belongs to no chosen set simply contributes nothing,
    which is what makes "run these nine cases" work across a multi-set choice.
    """
    statement = (
        select(EvalCase)
        .join(SetMembership, col(SetMembership.case_id) == col(EvalCase.id))
        .where(SetMembership.set_id == set_id, col(EvalCase.deleted_at).is_(None))
    )
    if case_ids is not None:
        if not case_ids:
            return []
        statement = statement.where(col(EvalCase.id).in_(case_ids))
    return list(session.exec(statement.order_by(col(SetMembership.position))).all())
