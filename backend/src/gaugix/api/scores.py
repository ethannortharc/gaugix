"""Human scoring, re-scoring, the review queue and the rubric library (PRD F4)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session, col, select

from gaugix.config import redact_for_display
from gaugix.db import get_session
from gaugix.domain import RunStatus
from gaugix.errors import NotFoundError, ValidationError
from gaugix.models.runs import Run, RunItem
from gaugix.models.scores import Score
from gaugix.repo import get_or_404
from gaugix.schemas.runs import ScoreRead
from gaugix.scoring import rescore as rescore_module
from gaugix.scoring.judge_config import default_judge_executor
from gaugix.scoring.service import BUILTIN_RUBRICS, latest_scores, submit_human_score

router = APIRouter(tags=["scores"])

SessionDep = Annotated[Session, Depends(get_session)]


class HumanScoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scorer_index: int = Field(default=0, ge=0)
    passed: bool | None = None
    value: float | None = Field(default=None, ge=0, le=100)
    note: str = ""


class HumanScoreResponse(BaseModel):
    ok: bool
    verdict: bool | None
    score_value: float | None
    needs_human: bool
    status: str
    disagreed_with_machine: bool = Field(
        description="True when the human overturned an auto/judge verdict — the calibration signal"
    )


class RescoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: int | None = None
    item_ids: list[int] = Field(default_factory=list)
    only_failing: bool = False
    scorer_indices: list[int] | None = None
    refresh_config: bool = Field(
        default=True,
        description="Pick up the case's current scoring config first (PRD F4.3)",
    )


class RescoreResponse(BaseModel):
    ok: bool
    items_rescored: int
    items_skipped: int
    verdict_changes: int
    configs_refreshed: int = 0
    details: list[dict[str, Any]] = Field(default_factory=list)


class QueueItem(BaseModel):
    """One item waiting on a human score, with enough context to tell it apart.

    Several cases can share a title and an executor — a benchmark install
    guarantees it — so the queue also carries which run and set it came from,
    what the automatic scorers already concluded, and when it was produced.
    """

    item_id: int
    run_id: int
    run_name: str
    title: str
    executor_key: str
    set_id: int | None = None
    set_name: str
    instructions: str | None = None
    scorer_index: int = 0
    #: What the machine thought, so a reviewer can spot disagreement early.
    auto_verdict: bool | None = None
    auto_score: float | None = None
    updated_at: datetime


class RubricRead(BaseModel):
    key: str
    name: str
    text: str
    builtin: bool = True


def to_score_read(score: Score) -> ScoreRead:
    return ScoreRead(
        id=score.id or 0,
        scorer_index=score.scorer_index,
        scorer_type=score.scorer_type,
        scorer_config_hash=score.scorer_config_hash,
        passed=score.passed,
        value=score.value,
        rationale=redact_for_display(score.rationale),
        source=score.source,
        judge_meta=redact_for_display(score.judge_meta),
        version=score.version,
        created_at=score.created_at,
    )


def load_item_scores(session: Session, item_id: int) -> list[ScoreRead]:
    """Latest score per scorer index — imported by the runs router."""
    latest = latest_scores(session, item_id)
    return [to_score_read(latest[index]) for index in sorted(latest)]


@router.get("/items/{item_id}/scores", response_model=list[ScoreRead])
def get_item_scores(
    item_id: int, session: SessionDep, history: bool = Query(default=False)
) -> list[ScoreRead]:
    """Latest score per scorer, or the full version history with `?history=true`."""
    get_or_404(session, RunItem, item_id, "Item")
    if not history:
        return load_item_scores(session, item_id)

    rows = session.exec(
        select(Score)
        .where(Score.run_item_id == item_id)
        .order_by(col(Score.scorer_index), col(Score.version))
    ).all()
    return [to_score_read(row) for row in rows]


@router.post("/items/{item_id}/human-score", response_model=HumanScoreResponse)
def post_human_score(
    item_id: int, payload: HumanScoreRequest, session: SessionDep
) -> HumanScoreResponse:
    """Record your judgement. It overrides the machine for that scorer (PRD F4.4)."""
    item = get_or_404(session, RunItem, item_id, "Item")
    _ensure_runs_idle(session, {item.run_id})
    if payload.passed is None and payload.value is None:
        raise ValidationError("provide `passed` and/or `value`")

    try:
        outcome, disagreed = submit_human_score(
            session,
            item,
            payload.scorer_index,
            payload.passed,
            payload.value,
            payload.note,
        )
    except IndexError as exc:
        raise ValidationError(str(exc)) from exc

    session.refresh(item)
    return HumanScoreResponse(
        ok=True,
        verdict=outcome.verdict,
        score_value=outcome.score_value,
        needs_human=outcome.needs_human,
        status=item.status,
        disagreed_with_machine=disagreed,
    )


@router.get("/review-queue", response_model=list[QueueItem])
def review_queue(
    session: SessionDep,
    response: Response,
    run_id: int | None = Query(default=None),
    set_id: int | None = Query(default=None),
    executor_key: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> list[QueueItem]:
    """Everything waiting on a human score (PRD F4.4)."""
    statement = select(RunItem).where(col(RunItem.needs_human).is_(True))
    if run_id is not None:
        statement = statement.where(RunItem.run_id == run_id)
    if set_id is not None:
        statement = statement.where(RunItem.set_id == set_id)
    if executor_key is not None:
        statement = statement.where(RunItem.executor_key == executor_key)

    # The true total, not the page length. Reporting the page as the total made
    # a queue longer than the limit look complete.
    total = len(session.exec(statement).all())
    rows = session.exec(statement.order_by(col(RunItem.id)).limit(limit).offset(offset)).all()
    response.headers["X-Total-Count"] = str(total)

    run_ids = {item.run_id for item in rows}
    names = {
        run.id: run.name
        for run in session.exec(select(Run).where(col(Run.id).in_(run_ids))).all()
        if run.id is not None
    }

    out: list[QueueItem] = []
    for item in rows:
        index, instructions = _human_scorer(item)
        out.append(
            QueueItem(
                item_id=item.id or 0,
                run_id=item.run_id,
                run_name=names.get(item.run_id, ""),
                title=item.title,
                executor_key=item.executor_key,
                set_id=item.set_id,
                set_name=item.set_name,
                instructions=instructions,
                scorer_index=index,
                auto_verdict=item.verdict,
                auto_score=item.score_value,
                updated_at=item.updated_at,
            )
        )
    return out


def _human_scorer(item: RunItem) -> tuple[int, str | None]:
    """Index and instructions of the first unresolved human scorer."""
    for index, spec in enumerate(item.case_snapshot.scoring):
        if str(spec.type) == "human":
            instructions = spec.params.get("instructions")
            return index, str(instructions) if instructions else None
    return 0, None


@router.post("/rescore", response_model=RescoreResponse)
async def rescore(payload: RescoreRequest, session: SessionDep) -> RescoreResponse:
    """Re-run scorers against stored outputs. Never re-invokes a model (PRD F4.3)."""
    rescore_module.validate_selection(payload.run_id, payload.item_ids)

    item_ids = list(payload.item_ids)
    if payload.run_id is not None:
        get_or_404(session, Run, payload.run_id, "Run")
        item_ids = rescore_module.items_for_run(
            session, payload.run_id, only_failing=payload.only_failing
        )

    selected_run_ids = {
        item.run_id
        for item in session.exec(select(RunItem).where(col(RunItem.id).in_(item_ids))).all()
    }
    if payload.run_id is not None:
        selected_run_ids.add(payload.run_id)
    _ensure_runs_idle(session, selected_run_ids)

    report = await rescore_module.rescore_items(
        session,
        item_ids,
        judge_executor=default_judge_executor(session),
        scorer_indices=payload.scorer_indices,
        refresh_config=payload.refresh_config,
    )

    # Counters drift once verdicts change, so rebuild them from the items.
    if payload.run_id is not None:
        from gaugix.engine.runner import recompute_totals

        run = session.get(Run, payload.run_id)
        if run is not None:
            run.totals = recompute_totals(session, payload.run_id)
            session.add(run)
            session.commit()

    return RescoreResponse(
        ok=True,
        items_rescored=report.items_rescored,
        items_skipped=report.items_skipped,
        verdict_changes=report.verdict_changes,
        configs_refreshed=report.configs_refreshed,
        details=report.details,
    )


def _ensure_runs_idle(session: Session, run_ids: set[int]) -> None:
    """Keep live-run state transitions exclusively owned by the runner."""
    if not run_ids:
        return
    from gaugix.engine.runner import registry

    active = [
        run.id or 0
        for run in session.exec(select(Run).where(col(Run.id).in_(run_ids))).all()
        if run.status == str(RunStatus.running) or registry.is_active(run.id or 0)
    ]
    if active:
        joined = ", ".join(str(run_id) for run_id in sorted(active))
        raise ValidationError(
            f"cannot score run(s) {joined} while execution is active; wait for completion"
        )


@router.get("/rubrics", response_model=list[RubricRead])
def list_rubrics(session: SessionDep) -> list[RubricRead]:
    """Built-in rubrics plus anything the user saved (PRD F4.5)."""
    from gaugix.api.settings import read_setting

    out = [
        RubricRead(key=key, name=value["name"], text=value["text"], builtin=True)
        for key, value in BUILTIN_RUBRICS.items()
    ]
    custom = read_setting(session, "rubrics", {}) or {}
    if isinstance(custom, dict):
        out.extend(
            RubricRead(key=str(key), name=str(key), text=str(text), builtin=False)
            for key, text in custom.items()
        )
    return out


class RubricUpsert(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1)
    text: str = Field(min_length=1)


@router.put("/rubrics", response_model=list[RubricRead])
def upsert_rubric(payload: RubricUpsert, session: SessionDep) -> list[RubricRead]:
    from gaugix.api.settings import read_setting, write_setting

    if payload.key in BUILTIN_RUBRICS:
        raise ValidationError(f"{payload.key!r} is a built-in rubric; choose another name")

    custom = read_setting(session, "rubrics", {}) or {}
    if not isinstance(custom, dict):
        custom = {}
    custom[payload.key] = payload.text
    write_setting(session, "rubrics", custom)
    session.commit()
    return list_rubrics(session)


@router.delete("/rubrics/{key}", response_model=list[RubricRead])
def delete_rubric(key: str, session: SessionDep) -> list[RubricRead]:
    """Remove a saved rubric. Built-ins are not removable — they ship with Gaugix.

    Scorers pointing at it by `rubric_ref` will report an unresolved rubric at
    scoring time rather than silently grading against nothing; preflight catches
    that before a run starts.
    """
    from gaugix.api.settings import read_setting, write_setting

    if key in BUILTIN_RUBRICS:
        raise ValidationError(f"{key!r} is built in and cannot be deleted")

    custom = read_setting(session, "rubrics", {}) or {}
    if not isinstance(custom, dict) or key not in custom:
        raise NotFoundError(f"no saved rubric named {key!r}")
    del custom[key]
    write_setting(session, "rubrics", custom)
    session.commit()
    return list_rubrics(session)
