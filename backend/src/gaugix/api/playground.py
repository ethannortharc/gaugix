"""Manual executor invocation before a user commits an evaluation case."""

from __future__ import annotations

import asyncio
import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlmodel import Session

from gaugix.db import get_session
from gaugix.domain import CaseSnapshot, HarnessError, InvokeContext
from gaugix.errors import NotFoundError
from gaugix.harness import get as get_harness
from gaugix.schemas.playground import (
    PlaygroundArtifactRead,
    PlaygroundRequest,
    PlaygroundResponse,
)
from gaugix.scoring.judge_config import executor_snapshot

router = APIRouter(prefix="/playground", tags=["playground"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.post("/invoke", response_model=PlaygroundResponse)
async def invoke(payload: PlaygroundRequest, session: SessionDep) -> PlaygroundResponse:
    """Invoke once without creating a Run, RunItem or Attempt.

    This is deliberately the same executor/harness seam as a formal run. The
    only differences are that the conversation is supplied directly and the
    result is returned immediately for human inspection.
    """
    executor = executor_snapshot(session, payload.executor_id)
    if executor is None:
        raise NotFoundError(f"Executor {payload.executor_id} does not exist")

    harness = get_harness(executor.harness.kind)
    case = CaseSnapshot(title="Playground", input=payload.messages)
    ctx = InvokeContext(
        harness_config=executor.harness.config,
        params={**executor.effective_params(), **payload.params},
        timeout_s=payload.timeout_s,
        purpose="playground",
    )
    try:
        async with asyncio.timeout(payload.timeout_s):
            result = await harness.invoke(case, executor.model, ctx)
    except TimeoutError:
        return PlaygroundResponse(
            ok=False,
            executor_key=executor.key,
            error=f"invocation exceeded {payload.timeout_s:g}s",
            error_kind="timeout",
        )
    except HarnessError as exc:
        return PlaygroundResponse(
            ok=False,
            executor_key=executor.key,
            error=exc.message,
            error_kind=exc.kind,
        )

    return PlaygroundResponse(
        ok=True,
        executor_key=executor.key,
        output_text=result.output_text,
        parsed_output=_parse_json(result.output_text),
        messages=result.messages,
        usage=result.usage,
        raw=result.raw,
        artifacts=[
            PlaygroundArtifactRead(kind=item.kind, filename=item.filename, mime=item.mime)
            for item in result.artifacts
        ],
    )


def _parse_json(value: str) -> Any | None:
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
