"""Run builder, lifecycle, item drill-down and the SSE event stream (PRD F3, F5.1)."""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlmodel import Session, col, func, select
from sse_starlette.sse import EventSourceResponse

from gaugix import coverage
from gaugix.api.artifacts import to_read as artifact_read
from gaugix.artifacts import store as artifact_store
from gaugix.compare import set_trends
from gaugix.db import get_engine, get_session
from gaugix.domain import ItemStatus, Pricing, RunStatus
from gaugix.engine import planner
from gaugix.engine.events import bus
from gaugix.engine.preflight import Preflight, preflight
from gaugix.engine.runner import (
    cancel_run,
    recompute_totals,
    registry,
    rerun_from,
    retry_item,
    schedulable_item_ids,
    start_run,
)
from gaugix.errors import ConflictError, NotFoundError, ValidationError
from gaugix.models.runs import Attempt, Run, RunItem
from gaugix.repo import get_or_404
from gaugix.schemas.runs import (
    AttemptRead,
    BaselineRequest,
    CancelResponse,
    ErrorKindCount,
    JudgeClassCount,
    LaneCounts,
    PreflightFinding,
    PreflightRead,
    RerunFromResponse,
    ResumeRequest,
    ResumeResponse,
    RunCreate,
    RunItemDetail,
    RunItemRead,
    RunPreview,
    RunPreviewRequest,
    RunRead,
    SetTrend,
)

router = APIRouter(tags=["runs"])

SessionDep = Annotated[Session, Depends(get_session)]

HEARTBEAT_S = 15.0


def _heartbeat_s() -> float:
    """Seconds between SSE keepalives. Overridable so tests need not wait 15s."""
    return float(os.environ.get("GAUGIX_SSE_HEARTBEAT_S", HEARTBEAT_S))


def _run_is_finished(run_id: int) -> bool:
    """Whether the run has reached a terminal status and no runner is active."""
    if registry.is_active(run_id):
        return False
    with Session(get_engine()) as session:
        run = session.get(Run, run_id)
        return run is None or run.is_terminal


# -- serialisation -------------------------------------------------------------


def _resumable_counts(session: Session, run_ids: list[int]) -> dict[int, int]:
    """How many items a resume would actually schedule, per run.

    `is_resumable` only says the *status* permits a resume; a completed run
    passes that test and has nothing left to do. Offering Resume there produced
    a button whose only outcome was "Nothing to resume", so the count travels
    with the run and the UI hides the button at zero (D-039).
    """
    if not run_ids:
        return {}
    rows = session.exec(
        select(RunItem.run_id, RunItem.status).where(col(RunItem.run_id).in_(run_ids))
    ).all()
    counts = dict.fromkeys(run_ids, 0)
    schedulable = {str(ItemStatus.pending), str(ItemStatus.error), str(ItemStatus.skipped)}
    for run_id, status in rows:
        if status in schedulable:
            counts[run_id] = counts.get(run_id, 0) + 1
    return counts


def to_run_read(run: Run, *, resumable_items: int) -> RunRead:
    """Serialise a run. `resumable_items` comes from :func:`_resumable_counts`.

    Passed in rather than computed here so listing 50 runs costs one query
    rather than 50.
    """
    active = registry.is_active(run.id or 0)
    thin = coverage.partial_sets(run.config)
    return RunRead(
        id=run.id or 0,
        name=run.name,
        status=run.status,
        parent_run_id=run.parent_run_id,
        config=run.config,
        totals=run.totals,
        is_baseline_for=run.is_baseline_for,
        error=run.error,
        started_at=run.started_at,
        finished_at=run.finished_at,
        created_at=run.created_at,
        updated_at=run.updated_at,
        is_active=active,
        resumable_items=resumable_items,
        # Both conditions, not just the status: a completed run is "resumable"
        # by status and has nothing to schedule.
        is_resumable=not active and run.is_resumable and resumable_items > 0,
        is_partial=bool(thin),
        partial_coverage=[f"{c.set_name}: {c.describe()}" for c in thin],
    )


def _one(session: Session, run: Run) -> RunRead:
    """Serialise a single run, resolving its resumable count."""
    counts = _resumable_counts(session, [run.id] if run.id is not None else [])
    return to_run_read(run, resumable_items=counts.get(run.id or 0, 0))


def to_item_read(item: RunItem) -> RunItemRead:
    return RunItemRead(
        id=item.id or 0,
        run_id=item.run_id,
        set_id=item.set_id,
        set_name=item.set_name,
        case_id=item.case_id,
        executor_key=item.executor_key,
        position=item.position,
        title=item.title,
        status=item.status,
        verdict=item.verdict,
        score_value=item.score_value,
        needs_human=item.needs_human,
        error=item.error,
        updated_at=item.updated_at,
    )


def to_attempt_read(attempt: Attempt) -> AttemptRead:
    return AttemptRead(
        id=attempt.id or 0,
        n=attempt.n,
        status=attempt.status,
        output_text=attempt.output_text,
        messages=attempt.messages,
        prompt_tokens=attempt.prompt_tokens,
        completion_tokens=attempt.completion_tokens,
        cost_usd=attempt.cost_usd,
        latency_ms=attempt.latency_ms,
        error=attempt.error,
        error_kind=attempt.error_kind,
        retries=attempt.retries,
        superseded=attempt.superseded,
        created_at=attempt.created_at,
    )


# -- builder -------------------------------------------------------------------


@router.post("/runs/preview", response_model=RunPreview)
def preview_run(payload: RunPreviewRequest, session: SessionDep) -> RunPreview:
    """Matrix preview with an estimated cost (PRD F3.1)."""
    if not payload.set_ids or not payload.executor_ids:
        return RunPreview(
            sets=[],
            executors=[],
            case_count=0,
            executor_count=0,
            item_count=0,
            suggested_name="",
        )
    data = planner.preview(session, payload.set_ids, payload.executor_ids, payload.case_ids)
    return RunPreview(**data, estimated_cost_usd=_estimate_cost(session, payload, data))


def _estimate_cost(
    session: Session, payload: RunPreviewRequest, data: dict[str, Any]
) -> float | None:
    """Rough pre-run cost, or None when any executor's pricing is unknown.

    A partial estimate would be worse than none: it would read as "this run is
    cheap" when the expensive model is exactly the one we could not price.
    """
    from gaugix.models.executors import Executor, ModelProfile

    #: Coarse per-item guess; the run page shows the real number as it accrues.
    assumed_prompt_tokens = 400
    assumed_completion_tokens = 400

    total = 0.0
    for executor_id in payload.executor_ids:
        executor = session.get(Executor, executor_id)
        if executor is None:
            return None
        model = session.get(ModelProfile, executor.model_profile_id)
        if model is None:
            return None
        if str(model.provider) == "fake":
            continue
        pricing: Pricing | None = model.pricing
        if pricing is None:
            return None
        total += (
            data["case_count"]
            * (
                assumed_prompt_tokens * pricing.input_per_1m
                + assumed_completion_tokens * pricing.output_per_1m
            )
            / 1_000_000
        )
    return round(total, 6)


@router.post("/runs/preflight", response_model=PreflightRead)
def run_preflight(payload: RunPreviewRequest, session: SessionDep) -> PreflightRead:
    """Everything wrong with this run that is knowable for free (PRD F3.1).

    Declared above `/runs/{run_id}` and safe to call on every change: it reads,
    validates and estimates, but never writes and never calls a model.
    """
    return _to_preflight_read(
        preflight(
            session,
            payload.set_ids,
            payload.executor_ids,
            payload.case_ids,
            auto_score=payload.auto_score,
        )
    )


def _to_preflight_read(result: Preflight) -> PreflightRead:
    return PreflightRead(
        ok=result.ok,
        findings=[PreflightFinding(**asdict(f)) for f in result.findings],
        case_count=result.case_count,
        executor_count=result.executor_count,
        item_count=result.item_count,
        estimated_cost_usd=result.estimated_cost_usd,
        cost_assumptions=result.cost_assumptions,
        judge_call_count=result.judge_call_count,
        estimated_judge_cost_usd=result.estimated_judge_cost_usd,
        requires_code_execution=result.requires_code_execution,
        code_execution_sets=result.code_execution_sets,
    )


@router.post("/runs", response_model=RunRead, status_code=201)
async def create_run(payload: RunCreate, session: SessionDep) -> RunRead:
    """Plan a run (one transaction), then optionally launch it.

    Preflight runs here as well as in the builder. The UI checking first is a
    courtesy; this is the rule — otherwise a script posting straight to `/runs`
    skips every guard the builder shows a person (D-048).
    """
    checks = preflight(
        session,
        payload.set_ids,
        payload.executor_ids,
        payload.case_ids,
        auto_score=payload.auto_score,
    )
    if not checks.ok:
        blockers = [f for f in checks.findings if f.severity == "blocker"]
        raise ValidationError(
            "this run cannot produce a usable result: " + "; ".join(f.message for f in blockers),
            details={"findings": [asdict(f) for f in blockers]},
        )
    if checks.requires_code_execution and not payload.accept_code_execution:
        raise ValidationError(
            "Scoring this run executes model-written code on this machine, outside any "
            f"sandbox ({', '.join(checks.code_execution_sets)}). Resend with "
            "accept_code_execution=true to accept that.",
            details={"code_execution_sets": checks.code_execution_sets},
        )

    planned = planner.plan_run(
        session,
        planner.PlanRequest(
            set_ids=payload.set_ids,
            executor_ids=payload.executor_ids,
            name=payload.name,
            concurrency=payload.concurrency,
            auto_score=payload.auto_score,
            parent_run_id=payload.parent_run_id,
            case_ids=payload.case_ids,
        ),
    )
    run_id = planned.run.id or 0

    if payload.start:
        await start_run(get_engine(), run_id)
        session.expire_all()
        run = session.get(Run, run_id)
        if run is not None:
            return _one(session, run)
    return _one(session, planned.run)


# -- listing & detail ----------------------------------------------------------


@router.get("/runs", response_model=list[RunRead])
def list_runs(
    session: SessionDep,
    response: Response,
    status: list[str] | None = Query(default=None),
    set_id: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[RunRead]:
    statement = select(Run)
    if status:
        statement = statement.where(col(Run.status).in_(status))
    if set_id is not None:
        statement = statement.where(col(Run.config_json).contains(f'"id": {set_id}'))

    total = len(session.exec(statement).all())
    rows = session.exec(statement.order_by(col(Run.id).desc()).limit(limit).offset(offset)).all()
    response.headers["X-Total-Count"] = str(total)
    counts = _resumable_counts(session, [r.id for r in rows if r.id is not None])
    return [to_run_read(r, resumable_items=counts.get(r.id or 0, 0)) for r in rows]


@router.get("/runs/trends", response_model=list[SetTrend])
def get_set_trends(
    session: SessionDep,
    limit: int = Query(default=10, ge=1, le=100),
    include_partial: bool = Query(
        default=False,
        description="Include runs that covered only part of a set. Off by default.",
    ),
) -> list[SetTrend]:
    """Pass rate per set over the most recent runs (PRD F5.1).

    Declared above `/runs/{run_id}` so the literal path is matched first. The
    dashboard needs per-set numbers: deriving a set's trend from its run's
    overall rate makes every set in a multi-set run share one line, and mixing
    in partial runs makes the line describe a different population at every
    point (D-053).
    """
    return [
        SetTrend.model_validate(entry)
        for entry in set_trends(session, limit_runs=limit, include_partial=include_partial)
    ]


@router.get("/runs/{run_id}", response_model=RunRead)
def get_run(run_id: int, session: SessionDep) -> RunRead:
    return _one(session, get_or_404(session, Run, run_id, "Run"))


@router.get("/runs/{run_id}/lanes", response_model=list[LaneCounts])
def get_lanes(run_id: int, session: SessionDep) -> list[LaneCounts]:
    """Per-executor status counts over the whole run, not the loaded page.

    The run page used to tally these from the items it had fetched, which the
    500-item default silently truncated: a 2,000-item run showed each lane as
    "500 of 500 done" while it was a quarter through (D-042).
    """
    get_or_404(session, Run, run_id, "Run")
    rows = session.exec(
        select(RunItem.executor_key, RunItem.status, func.count())
        .where(RunItem.run_id == run_id)
        .group_by(col(RunItem.executor_key), col(RunItem.status))
    ).all()

    lanes: dict[str, dict[str, int]] = {}
    for executor_key, status, count in rows:
        lanes.setdefault(executor_key, {})[status] = int(count)
    return [
        LaneCounts(executor_key=key, counts=counts, total=sum(counts.values()))
        for key, counts in sorted(lanes.items())
    ]


@router.get("/runs/{run_id}/items", response_model=list[RunItemRead])
def list_run_items(
    run_id: int,
    session: SessionDep,
    response: Response,
    status: list[str] | None = Query(default=None),
    executor_key: list[str] | None = Query(default=None),
    set_id: int | None = Query(default=None),
    verdict: bool | None = Query(default=None),
    needs_human: bool | None = Query(default=None),
    error_kind: list[str] | None = Query(default=None),
    q: str | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
) -> list[RunItemRead]:
    """The run page's item board — filterable on everything it displays (PRD F5.1)."""
    get_or_404(session, Run, run_id, "Run")

    statement = select(RunItem).where(RunItem.run_id == run_id)
    if status:
        statement = statement.where(col(RunItem.status).in_(status))
    if executor_key:
        statement = statement.where(col(RunItem.executor_key).in_(executor_key))
    if set_id is not None:
        statement = statement.where(RunItem.set_id == set_id)
    if verdict is not None:
        statement = statement.where(col(RunItem.verdict).is_(verdict))
    if needs_human is not None:
        statement = statement.where(col(RunItem.needs_human).is_(needs_human))
    if q:
        statement = statement.where(col(RunItem.case_snapshot_json).ilike(f"%{q}%"))
    if error_kind:
        # `error_kind` lives on the attempt, not the item — an item is "a timeout"
        # only by way of the attempt that timed out.
        statement = statement.where(
            col(RunItem.current_attempt_id).in_(
                select(Attempt.id).where(col(Attempt.error_kind).in_(error_kind))
            )
        )

    total = len(session.exec(statement).all())
    rows = session.exec(
        statement.order_by(col(RunItem.executor_key), col(RunItem.position))
        .limit(limit)
        .offset(offset)
    ).all()
    response.headers["X-Total-Count"] = str(total)
    return [to_item_read(i) for i in rows]


@router.get("/items/{item_id}", response_model=RunItemDetail)
def get_item(item_id: int, session: SessionDep) -> RunItemDetail:
    """Full drill-down: input, every attempt, every score, artifacts."""
    item = get_or_404(session, RunItem, item_id, "Item")
    snapshot = item.case_snapshot

    attempts = session.exec(
        select(Attempt).where(Attempt.run_item_id == item_id).order_by(col(Attempt.n))
    ).all()
    attempt_ids = [a.id for a in attempts if a.id is not None]
    run = session.get(Run, item.run_id)
    neighbours = _lane_neighbours(session, item)

    return RunItemDetail(
        **to_item_read(item).model_dump(),
        input=snapshot.input,
        reference=snapshot.reference,
        case_snapshot=snapshot,
        attempts=[to_attempt_read(a) for a in attempts],
        scores=_load_scores(session, item_id),
        artifacts=[
            artifact_read(a).model_dump()
            for a in artifact_store.artifacts_for_attempts(session, attempt_ids)
        ],
        run_name=run.name if run else "",
        **neighbours,
    )


def _lane_neighbours(session: Session, item: RunItem) -> dict[str, Any]:
    """The items either side of this one in its executor lane, and its place in it.

    Four small aggregate queries rather than the lane's item list: reading
    through the failures of a 5,000-item run is the normal way to use this page,
    and it must not cost 5,000 rows per arrow.
    """
    lane = (RunItem.run_id == item.run_id, RunItem.executor_key == item.executor_key)
    previous = session.exec(
        select(RunItem.id)
        .where(*lane, RunItem.position < item.position)
        .order_by(col(RunItem.position).desc())
        .limit(1)
    ).first()
    following = session.exec(
        select(RunItem.id)
        .where(*lane, RunItem.position > item.position)
        .order_by(col(RunItem.position))
        .limit(1)
    ).first()
    total = session.exec(select(func.count()).select_from(RunItem).where(*lane)).one()
    before = session.exec(
        select(func.count()).select_from(RunItem).where(*lane, RunItem.position < item.position)
    ).one()
    return {
        "prev_item_id": previous,
        "next_item_id": following,
        "lane_position": int(before) + 1,
        "lane_total": int(total),
    }


def _load_scores(session: Session, item_id: int) -> list[Any]:
    """Scores arrive in M3; until the table exists this is empty, not an error."""
    try:
        from gaugix.api.scores import load_item_scores
    except ImportError:
        return []
    scores: list[Any] = load_item_scores(session, item_id)
    return scores


# -- lifecycle -----------------------------------------------------------------


@router.post("/runs/{run_id}/cancel", response_model=CancelResponse)
async def cancel(run_id: int, session: SessionDep) -> CancelResponse:
    run = get_or_404(session, Run, run_id, "Run")
    if run.is_terminal and not registry.is_active(run_id):
        return CancelResponse(ok=False, status=run.status, message="run is already finished")

    await cancel_run(get_engine(), run_id)
    session.expire_all()
    refreshed = session.get(Run, run_id)
    return CancelResponse(
        ok=True, status=refreshed.status if refreshed else str(RunStatus.canceled)
    )


@router.post("/runs/{run_id}/resume", response_model=ResumeResponse)
async def resume(run_id: int, payload: ResumeRequest, session: SessionDep) -> ResumeResponse:
    """Re-execute only what is unfinished. `passed`/`failed` items are never redone."""
    run = get_or_404(session, Run, run_id, "Run")
    if registry.is_active(run_id):
        raise ConflictError(f"run {run_id} is already running")

    pending = schedulable_item_ids(session, run_id, payload.include_errors)
    if not pending:
        return ResumeResponse(
            ok=False,
            scheduled=0,
            status=run.status,
            message="nothing to resume — every item already has a kept result",
        )

    await start_run(get_engine(), run_id, include_errors=payload.include_errors)
    return ResumeResponse(ok=True, scheduled=len(pending), status=str(RunStatus.running))


@router.get("/runs/{run_id}/error-kinds", response_model=list[ErrorKindCount])
def get_error_kinds(run_id: int, session: SessionDep) -> list[ErrorKindCount]:
    """The error taxonomy actually present in this run, with counts (PRD F3.8).

    Built from the run rather than from the enum: offering a "rate limit" filter
    on a run that never hit one is a dead end dressed as a feature.
    """
    get_or_404(session, Run, run_id, "Run")
    rows = session.exec(
        select(Attempt.error_kind, func.count())
        .join(RunItem, col(RunItem.current_attempt_id) == col(Attempt.id))
        .where(RunItem.run_id == run_id, col(Attempt.error_kind).is_not(None))
        .group_by(col(Attempt.error_kind))
    ).all()
    counts = [ErrorKindCount(kind=str(kind), count=int(count)) for kind, count in rows if kind]
    counts.sort(key=lambda entry: (-entry.count, entry.kind))
    return counts


@router.get("/runs/{run_id}/judge-classes", response_model=list[JudgeClassCount])
def get_judge_classes(run_id: int, session: SessionDep) -> list[JudgeClassCount]:
    """How a class-graded judge split this run, with counts (PRD F5.1).

    SimpleQA grades into CORRECT / INCORRECT / NOT_ATTEMPTED, and the split
    between the last two is the benchmark's whole point — a model that knows
    what it does not know fails differently from one that invents. The
    catalogue told people to read the not-attempted share; until this existed
    the number was only in prose (D-057).

    Empty for runs whose scorers grade onto a scale, which is most of them.
    """
    get_or_404(session, Run, run_id, "Run")
    from gaugix.models.scores import Score

    rows = session.exec(
        select(Score)
        .join(RunItem, col(RunItem.id) == col(Score.run_item_id))
        .where(RunItem.run_id == run_id)
    ).all()

    # A re-score appends a version rather than replacing one, so counting every
    # row would count an item once per time it was graded. Only the newest
    # version of each (item, scorer) is this run's current answer.
    latest: dict[tuple[int, int], Score] = {}
    for score in rows:
        key = (score.run_item_id, score.scorer_index)
        if key not in latest or score.version > latest[key].version:
            latest[key] = score

    counts: dict[str, int] = {}
    for score in latest.values():
        named = (score.judge_meta or {}).get("classification")
        if isinstance(named, str) and named:
            counts[named] = counts.get(named, 0) + 1

    total = sum(counts.values())
    return [
        JudgeClassCount(
            name=name,
            count=count,
            share=round(100 * count / total, 1) if total else 0.0,
        )
        for name, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


@router.post("/runs/{run_id}/items/{item_id}/retry", response_model=RerunFromResponse)
async def retry_one_item(run_id: int, item_id: int, session: SessionDep) -> RerunFromResponse:
    """Re-execute just this item (PRD F3.6).

    The narrow form of rerun-from: a single rate-limited call does not justify
    re-running — and re-paying for — the whole tail of its lane.
    """
    get_or_404(session, Run, run_id, "Run")
    if registry.is_active(run_id):
        raise ConflictError("cancel the run before retrying part of it")

    try:
        retry_item(session, run_id, item_id)
    except ValueError as exc:
        raise NotFoundError(str(exc)) from exc

    await start_run(get_engine(), run_id)
    return RerunFromResponse(ok=True, affected=1, status=str(RunStatus.running))


@router.post("/runs/{run_id}/items/{item_id}/rerun-from", response_model=RerunFromResponse)
async def rerun_from_item(run_id: int, item_id: int, session: SessionDep) -> RerunFromResponse:
    """Re-execute this item and every later one in the same lane (PRD F3.6)."""
    get_or_404(session, Run, run_id, "Run")
    if registry.is_active(run_id):
        raise ConflictError("cancel the run before rerunning part of it")

    try:
        reset = rerun_from(session, run_id, item_id)
    except ValueError as exc:
        raise NotFoundError(str(exc)) from exc

    if not reset:
        return RerunFromResponse(
            ok=False, affected=0, status="unchanged", message="nothing to rerun"
        )

    await start_run(get_engine(), run_id)
    return RerunFromResponse(ok=True, affected=len(reset), status=str(RunStatus.running))


@router.post("/runs/{run_id}/rerun", response_model=RunRead, status_code=201)
async def rerun_whole_run(run_id: int, session: SessionDep) -> RunRead:
    """Start a fresh run with the same sets and executors, linked as a child (PRD F3.7)."""
    parent = get_or_404(session, Run, run_id, "Run")
    config = parent.config
    set_ids = [int(s["id"]) for s in config.get("sets", []) if s.get("id") is not None]
    executor_ids = [
        int(e["executor_id"])
        for e in config.get("executors", [])
        if e.get("executor_id") is not None
    ]
    if not set_ids or not executor_ids:
        raise ValidationError("this run's sets or executors no longer exist, so it cannot be rerun")

    return await create_run(
        RunCreate(
            set_ids=set_ids,
            executor_ids=executor_ids,
            name=f"{parent.name} (rerun)",
            concurrency=int(config.get("concurrency", 4)),
            auto_score=bool(config.get("auto_score", True)),
            parent_run_id=run_id,
            start=True,
            # A partial run reruns the same part. Rerunning the whole set instead
            # would silently change what the two runs compare.
            case_ids=config.get("case_ids"),
            # The parent already carried this acknowledgement; a rerun of an
            # accepted run must not stall on re-accepting it.
            accept_code_execution=True,
        ),
        session,
    )


@router.get("/runs/{run_id}/report")
def get_run_report(run_id: int, session: SessionDep) -> Response:
    """This run as one self-contained HTML file — opens offline, forever (PRD F5.5)."""
    from gaugix.report.build import build_run_report

    run = get_or_404(session, Run, run_id, "Run")
    html = build_run_report(session, run)
    return Response(
        content=html,
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="gaugix-run-{run_id}.html"'},
    )


@router.post("/runs/{run_id}/baseline", response_model=RunRead)
def set_baseline(run_id: int, payload: BaselineRequest, session: SessionDep) -> RunRead:
    """Mark (or unmark) this run as the baseline for the given sets (PRD F5.3).

    A run that covered part of a set cannot be that set's baseline by accident.
    Everything downstream — the diff, the dashboard, "did this regress" —
    compares against the baseline as though it described the whole set, and a
    baseline over two of five cases quietly redefines what regression means
    (D-053). It is still allowed, with `allow_partial`, because a deliberate
    baseline over a chosen slice is a real thing to want.
    """
    run = get_or_404(session, Run, run_id, "Run")
    current = set(run.is_baseline_for)
    covers = coverage.of_run(run.config)

    # A run can only be the baseline for sets it actually covered. Without this
    # an unrelated — or non-existent — set id was written straight into
    # `is_baseline_for`, and cleared whatever run was that set's real baseline
    # on the way (D-063).
    if not payload.unset:
        foreign = [s for s in payload.set_ids if s not in covers]
        if foreign:
            raise ValidationError(
                f"this run did not cover set(s) {', '.join(str(s) for s in foreign)}, "
                "so it cannot be their baseline.",
                details={"run_set_ids": sorted(covers), "rejected": foreign},
            )

    if not payload.unset and not payload.allow_partial:
        thin = [covers[s] for s in payload.set_ids if s in covers and covers[s].is_partial]
        if thin:
            listed = "; ".join(f"{c.set_name} ({c.describe()})" for c in thin)
            raise ValidationError(
                f"this run covered only part of {listed}, so it cannot describe the whole set. "
                "Resend with allow_partial=true to use it as a baseline anyway.",
                details={"partial_sets": [c.set_id for c in thin]},
            )

    if payload.unset:
        run.is_baseline_for = sorted(current - set(payload.set_ids))
    else:
        # A set has exactly one baseline; clear the flag from any other run first.
        others = session.exec(select(Run).where(Run.id != run_id)).all()
        for other in others:
            overlap = set(other.is_baseline_for) & set(payload.set_ids)
            if overlap:
                other.is_baseline_for = sorted(set(other.is_baseline_for) - overlap)
                session.add(other)
        run.is_baseline_for = sorted(current | set(payload.set_ids))

    run.touch()
    session.add(run)
    session.commit()
    session.refresh(run)
    return _one(session, run)


@router.delete("/runs/{run_id}", response_model=CancelResponse)
async def delete_run(run_id: int, session: SessionDep) -> CancelResponse:
    """Delete a finished run and everything under it."""
    run = get_or_404(session, Run, run_id, "Run")
    if registry.is_active(run_id):
        raise ConflictError("cancel the run before deleting it")

    items = session.exec(select(RunItem).where(RunItem.run_id == run_id)).all()
    item_ids = [i.id for i in items if i.id is not None]
    if item_ids:
        _delete_scores(session, item_ids)
        attempts = session.exec(select(Attempt).where(col(Attempt.run_item_id).in_(item_ids))).all()
        attempt_ids = [a.id for a in attempts if a.id is not None]
        for artifact in artifact_store.artifacts_for_attempts(session, attempt_ids):
            session.delete(artifact)
        for attempt in attempts:
            session.delete(attempt)
        session.flush()
    for item in items:
        session.delete(item)
    session.flush()
    session.delete(run)
    session.commit()
    artifact_store.remove_run_artifacts(run_id)
    return CancelResponse(ok=True, status="deleted")


def _delete_scores(session: Session, item_ids: list[int]) -> None:
    try:
        from gaugix.models.scores import Score
    except ImportError:
        return
    rows = session.exec(select(Score).where(col(Score.run_item_id).in_(item_ids))).all()
    for row in rows:
        session.delete(row)
    session.flush()


@router.post("/runs/{run_id}/recount", response_model=RunRead)
def recount(run_id: int, session: SessionDep) -> RunRead:
    """Rebuild a run's cached counters from its items (repair hatch)."""
    run = get_or_404(session, Run, run_id, "Run")
    run.totals = recompute_totals(session, run_id)
    run.touch()
    session.add(run)
    session.commit()
    session.refresh(run)
    return _one(session, run)


# -- live events ---------------------------------------------------------------


@router.get("/runs/{run_id}/events")
async def run_events(run_id: int, request: Request, session: SessionDep) -> EventSourceResponse:
    """SSE stream of run deltas.

    Replays nothing: the UI fetches full state first, then subscribes. Every event
    carries a monotonic `seq` so a reconnecting client can drop stale deltas.
    """
    get_or_404(session, Run, run_id, "Run")

    async def publisher() -> Any:
        queue = bus.subscribe(run_id)
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=_heartbeat_s())
                except TimeoutError:
                    # Idle. If the run has finished and nothing is queued, close the
                    # stream — a terminal run has no more deltas to send, and holding
                    # the connection open forever leaks a task per reopened tab.
                    if _run_is_finished(run_id) and queue.empty():
                        yield {"event": "end", "data": json.dumps({"run_id": run_id})}
                        break
                    # Otherwise keep the connection warm against idle proxies.
                    yield {"event": "ping", "data": "{}"}
                    continue
                payload = event.to_sse()
                yield {"event": payload["event"], "data": json.dumps(payload["data"])}
        finally:
            bus.unsubscribe(run_id, queue)

    return EventSourceResponse(publisher(), ping=None)


__all__ = ["ItemStatus", "NotFoundError", "ValidationError", "router"]
