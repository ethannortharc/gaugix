"""Task-aware metrics endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from gaugix.db import get_session
from gaugix.evaluation import summarize_run
from gaugix.schemas.evaluation import RunEvaluationRead

router = APIRouter(tags=["evaluation"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/runs/{run_id}/metrics", response_model=RunEvaluationRead)
def get_run_metrics(
    run_id: int,
    session: SessionDep,
    set_id: int | None = Query(default=None),
    executor: str | None = Query(default=None),
    node_id: int | None = Query(default=None),
) -> RunEvaluationRead:
    return summarize_run(
        session,
        run_id,
        set_id=set_id,
        executor_key=executor,
        node_id=node_id,
    )
