"""Comparison endpoints: diff, leaderboard, matrix, aggregate (PRD F5.2–F5.4).

Thin by design — every number comes from `gaugix.compare`, which reads run items
and computes on the spot. These endpoints choose the inputs and shape the reply.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlmodel import Session, col, select

from gaugix.compare import (
    CHANGE_KINDS,
    aggregate_matrix,
    baselines_for_sets,
    diff_runs,
    group_sets_by_baseline,
    leaderboard,
    matrix,
)
from gaugix.config import redact_for_display
from gaugix.db import get_session
from gaugix.errors import NotFoundError, ValidationError
from gaugix.models.cases import EvalSet
from gaugix.models.runs import Run, RunItem
from gaugix.repo import get_or_404
from gaugix.report.build import build_comparison_report
from gaugix.schemas.compare import (
    AggregateMatrixRead,
    CompareOptions,
    CompareRunOption,
    DiffExecutors,
    DiffRead,
    LeaderboardRead,
    MatrixRead,
    NamedRef,
    SetCoverage,
    SideBySide,
)

router = APIRouter(prefix="/compare", tags=["compare"])

SessionDep = Annotated[Session, Depends(get_session)]
RunIds = Annotated[list[int], Query(alias="run_id")]
SetIds = Annotated[list[int] | None, Query(alias="set_id")]
ExecutorKeys = Annotated[list[str] | None, Query(alias="executor")]


def _require_runs(session: Session, run_ids: list[int]) -> None:
    if not run_ids:
        raise ValidationError("pick at least one run to compare")
    found = set(session.exec(select(Run.id).where(col(Run.id).in_(run_ids))).all())
    missing = [run_id for run_id in run_ids if run_id not in found]
    if missing:
        raise NotFoundError(f"no run with id {missing[0]}")


@router.get("/options", response_model=CompareOptions)
def compare_options(session: SessionDep) -> CompareOptions:
    """What is actually comparable — runs that produced items, and their sets.

    The picker is built from this rather than from every run ever created: a
    pending or empty run has nothing to compare and would only be a dead end.
    """
    items = session.exec(select(RunItem)).all()
    run_ids = {item.run_id for item in items}

    sets: dict[int, str] = {}
    executors: set[str] = set()
    sets_by_run: dict[int, set[int]] = {}
    for item in items:
        executors.add(item.executor_key)
        if item.set_id is not None:
            sets[item.set_id] = item.set_name
            sets_by_run.setdefault(item.run_id, set()).add(item.set_id)

    runs = [run for run in session.exec(select(Run)).all() if run.id in run_ids]
    runs.sort(key=lambda r: r.created_at, reverse=True)

    return CompareOptions(
        runs=[
            CompareRunOption(
                id=run.id,
                name=run.name,
                status=run.status,
                created_at=run.created_at,
                finished_at=run.finished_at,
                is_baseline_for=run.is_baseline_for,
                set_ids=sorted(sets_by_run.get(run.id, set())),
                totals=run.totals,
            )
            for run in runs
            if run.id is not None
        ],
        sets=[NamedRef(id=set_id, name=name) for set_id, name in sorted(sets.items())],
        executors=sorted(executors),
    )


@router.get("/diff", response_model=DiffRead)
def get_diff(
    session: SessionDep,
    run_id: Annotated[int, Query()],
    baseline_run_id: Annotated[int | None, Query()] = None,
    set_id: SetIds = None,
) -> DiffRead:
    """Regression diff against a baseline (PRD F5.3).

    With no explicit baseline, each set in the run is asked which run *it* has
    blessed. Sets do not have to agree: a run covering two sets can face two
    different baselines, and comparing one set's items against the other set's
    baseline would produce a confident, meaningless number. So the diff is
    scoped to one baseline's sets and `coverage` names every set left out and
    the baseline it would need (D-029).
    """
    run = get_or_404(session, Run, run_id, "Run")
    run_set_ids = _set_ids_for(session, run_id)
    requested_sets = [s for s in (set_id or run_set_ids) if s in run_set_ids] or run_set_ids
    resolved = baselines_for_sets(session, requested_sets, exclude_run_id=run_id)

    scoped_sets = requested_sets
    if baseline_run_id is None:
        groups = group_sets_by_baseline(resolved)
        if groups:
            baseline_run_id = groups[0].baseline_run_id
            scoped_sets = groups[0].set_ids
    else:
        # An explicit baseline still only covers the sets it was blessed for;
        # anything else it happens to contain is a coincidence, not a baseline.
        blessed = [s for s in requested_sets if resolved.get(s) == baseline_run_id]
        scoped_sets = blessed or requested_sets

    if baseline_run_id is None:
        return DiffRead(
            available=False,
            reason=(
                "No baseline to compare against yet. Mark a run as baseline for this "
                "set, or pick one explicitly."
            ),
            current_run_id=run_id,
            baseline_run_id=0,
            counts=dict.fromkeys(CHANGE_KINDS, 0),
            entries=[],
            executors=DiffExecutors(both=[], only_current=[], only_baseline=[]),
            coverage=_coverage(session, requested_sets, resolved, included=[]),
            pass_rate=SideBySide(current=None, baseline=None),
            mean_score=SideBySide(current=None, baseline=None),
        )
    if baseline_run_id == run_id:
        raise ValidationError("a run cannot be its own baseline")
    get_or_404(session, Run, baseline_run_id, "Baseline run")

    payload = diff_runs(session, run.id or 0, baseline_run_id, set_ids=scoped_sets or None)
    payload["coverage"] = [
        c.model_dump() for c in _coverage(session, requested_sets, resolved, included=scoped_sets)
    ]
    payload["scoped_set_ids"] = scoped_sets
    return DiffRead.model_validate(redact_for_display(payload))


def _set_ids_for(session: Session, run_id: int) -> list[int]:
    items = session.exec(select(RunItem).where(RunItem.run_id == run_id)).all()
    return sorted({item.set_id for item in items if item.set_id is not None})


def _coverage(
    session: Session,
    set_ids: list[int],
    resolved: dict[int, int],
    *,
    included: list[int],
) -> list[SetCoverage]:
    """Per-set baseline resolution, so an excluded set is visible rather than absent."""
    sets = session.exec(select(EvalSet).where(col(EvalSet.id).in_(set_ids))).all()
    names = {s.id: s.name for s in sets}
    run_names = {
        r.id: r.name
        for r in session.exec(select(Run).where(col(Run.id).in_(set(resolved.values())))).all()
    }
    covered = set(included)

    out: list[SetCoverage] = []
    for sid in set_ids:
        baseline = resolved.get(sid) or None
        reason: str | None = None
        if baseline is None:
            reason = "No run is marked baseline for this set."
        elif sid not in covered:
            reason = (
                f"This set's baseline is a different run ({run_names.get(baseline, baseline)}). "
                "Diff it separately."
            )
        out.append(
            SetCoverage(
                set_id=sid,
                set_name=names.get(sid, f"set {sid}"),
                baseline_run_id=baseline,
                baseline_run_name=run_names.get(baseline, "") if baseline else "",
                included=sid in covered,
                reason=reason,
            )
        )
    return out


@router.get("/leaderboard", response_model=LeaderboardRead)
def get_leaderboard(
    session: SessionDep,
    run_id: RunIds = None,  # type: ignore[assignment]
    set_id: SetIds = None,
    executor: ExecutorKeys = None,
) -> LeaderboardRead:
    """Executors ranked by pass rate, with the cost they charged for it (PRD F5.4)."""
    run_ids = run_id or []
    _require_runs(session, run_ids)
    return LeaderboardRead.model_validate(
        leaderboard(session, run_ids, set_ids=set_id, executor_keys=executor)
    )


@router.get("/matrix", response_model=MatrixRead)
def get_matrix(
    session: SessionDep,
    run_id: RunIds = None,  # type: ignore[assignment]
    set_id: SetIds = None,
    executor: ExecutorKeys = None,
) -> MatrixRead:
    """Cases × executors, with the verdict in each cell (PRD F5.2)."""
    run_ids = run_id or []
    _require_runs(session, run_ids)
    return MatrixRead.model_validate(
        redact_for_display(matrix(session, run_ids, set_ids=set_id, executor_keys=executor))
    )


@router.get("/report")
def get_comparison_report(
    session: SessionDep,
    run_id: RunIds = None,  # type: ignore[assignment]
    baseline_run_id: Annotated[int | None, Query()] = None,
) -> Response:
    """A comparison as one self-contained HTML file (PRD F5.5)."""
    run_ids = run_id or []
    _require_runs(session, run_ids)
    if baseline_run_id is not None:
        get_or_404(session, Run, baseline_run_id, "Baseline run")

    html = build_comparison_report(session, run_ids, baseline_run_id=baseline_run_id)
    stem = "-".join(str(rid) for rid in run_ids[:4])
    return Response(
        content=html,
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="gaugix-comparison-{stem}.html"'},
    )


@router.get("/aggregate", response_model=AggregateMatrixRead)
def get_aggregate(
    session: SessionDep,
    run_id: RunIds = None,  # type: ignore[assignment]
    set_id: SetIds = None,
    executor: ExecutorKeys = None,
) -> AggregateMatrixRead:
    """Sets × executors, with pass rate, mean score and cost per cell (PRD F5.2)."""
    run_ids = run_id or []
    _require_runs(session, run_ids)
    return AggregateMatrixRead.model_validate(
        aggregate_matrix(session, run_ids, set_ids=set_id, executor_keys=executor)
    )
