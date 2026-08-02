"""Artifact listing, content and comparison (PRD F6.1–F6.5).

Content is served with a **hard-locked content type**. An artifact is a file a
model wrote — untrusted by construction — and this server runs on the same
origin as the app. Handing the browser `text/html` with `Content-Type: text/html`
would let a generated page run scripts with the app's origin, read its state and
call its API. So every artifact leaves here as a download or as plain text, and
HTML previewing happens in a sandboxed iframe on the client, which cannot reach
back (PRD F6.2).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlmodel import Session, col, select

from gaugix.artifacts import execute, store
from gaugix.db import get_session
from gaugix.errors import NotFoundError, ValidationError
from gaugix.models.artifacts import Artifact
from gaugix.models.runs import Attempt, RunItem
from gaugix.repo import get_or_404
from gaugix.schemas.artifacts import (
    ArtifactCompare,
    ArtifactRead,
    ArtifactSide,
    ExecPlanRead,
    ExecRequest,
    ExecResultRead,
)

router = APIRouter(tags=["artifacts"])

SessionDep = Annotated[Session, Depends(get_session)]
ItemIds = Annotated[list[int], Query(alias="item_id")]

#: Text-ish types we will inline as UTF-8 for the viewer. Everything else
#: downloads. HTML is deliberately absent — see the module docstring.
INLINE_TEXT_PREFIXES = ("text/", "application/json", "application/xml", "application/yaml")
INLINE_TEXT_EXACT = {"application/toml", "application/sql", "application/javascript"}

#: Refuse to inline something enormous into a JSON response.
MAX_INLINE_BYTES = 2 * 1024 * 1024


def is_textual(mime: str) -> bool:
    if mime == "text/html":
        # Renderable, but only inside the client's sandboxed iframe.
        return True
    return mime.startswith(INLINE_TEXT_PREFIXES) or mime in INLINE_TEXT_EXACT


def to_read(artifact: Artifact) -> ArtifactRead:
    return ArtifactRead(
        id=artifact.id or 0,
        attempt_id=artifact.attempt_id,
        kind=artifact.kind,
        filename=artifact.filename,
        mime=artifact.mime,
        size_bytes=artifact.size_bytes,
        sha256=artifact.sha256,
        language=artifact.language,
        block_index=artifact.block_index,
        textual=is_textual(artifact.mime),
        created_at=artifact.created_at,
    )


@router.get("/items/{item_id}/artifacts", response_model=list[ArtifactRead])
def list_item_artifacts(item_id: int, session: SessionDep) -> list[ArtifactRead]:
    """Everything this item's attempts produced, newest attempt first."""
    item = get_or_404(session, RunItem, item_id, "Item")
    attempts = session.exec(
        select(Attempt).where(Attempt.run_item_id == item.id).order_by(col(Attempt.n).desc())
    ).all()
    attempt_ids = [a.id for a in attempts if a.id is not None]
    return [to_read(a) for a in store.artifacts_for_attempts(session, attempt_ids)]


@router.get("/artifacts/compare", response_model=ArtifactCompare)
def compare_artifacts(
    session: SessionDep,
    item_id: ItemIds = None,  # type: ignore[assignment]
) -> ArtifactCompare:
    """Two to four items' artifacts, side by side (PRD F6.5).

    Panes come back in the order asked for, so the caller controls the layout
    and a missing artifact set is an empty pane rather than a shifted one.
    """
    item_ids = item_id or []
    if not 2 <= len(item_ids) <= 4:
        raise ValidationError("side-by-side compare takes between 2 and 4 items")

    sides: list[ArtifactSide] = []
    for wanted in item_ids:
        item = session.get(RunItem, wanted)
        if item is None:
            raise NotFoundError(f"no item with id {wanted}")
        attempts = session.exec(
            select(Attempt).where(Attempt.run_item_id == wanted, col(Attempt.superseded).is_(False))
        ).all()
        attempt_ids = [a.id for a in attempts if a.id is not None]
        current = max(attempts, key=lambda a: a.n, default=None)
        sides.append(
            ArtifactSide(
                item_id=wanted,
                executor_key=item.executor_key,
                title=item.case_snapshot.title,
                run_id=item.run_id,
                status=item.status,
                verdict=item.verdict,
                score_value=item.score_value,
                output_text=current.output_text if current else "",
                artifacts=[to_read(a) for a in store.artifacts_for_attempts(session, attempt_ids)],
            )
        )
    return ArtifactCompare(sides=sides)


@router.get("/artifacts/{artifact_id}", response_model=ArtifactRead)
def get_artifact(artifact_id: int, session: SessionDep) -> ArtifactRead:
    return to_read(get_or_404(session, Artifact, artifact_id, "Artifact"))


@router.get("/artifacts/{artifact_id}/content")
def get_artifact_content(
    artifact_id: int,
    session: SessionDep,
    download: Annotated[bool, Query()] = False,
) -> Response:
    """The bytes, never served as an executable content type (see module docstring)."""
    artifact = get_or_404(session, Artifact, artifact_id, "Artifact")
    try:
        content = store.read_artifact(artifact)
    except (FileNotFoundError, ValueError) as exc:
        raise NotFoundError(str(exc)) from exc

    disposition = "attachment" if download or not is_textual(artifact.mime) else "inline"
    return Response(
        content=content,
        # Always neutralised: a model-authored file must never be handed to the
        # browser as something it will execute on this origin.
        media_type="text/plain; charset=utf-8" if not download else "application/octet-stream",
        headers={
            "Content-Disposition": f'{disposition}; filename="{artifact.filename}"',
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "X-Artifact-Mime": artifact.mime,
        },
    )


EXEC_WARNING = (
    "This program was written by a model. It runs as you, on your machine, with "
    "your files — Gaugix does not sandbox it. Read it before running it."
)


@router.get("/artifacts/{artifact_id}/exec-plan", response_model=ExecPlanRead)
def get_exec_plan(artifact_id: int, session: SessionDep) -> ExecPlanRead:
    """What would run, and the token that authorises exactly that (PRD F6.4)."""
    artifact = get_or_404(session, Artifact, artifact_id, "Artifact")
    try:
        plan = execute.plan(artifact)
    except execute.NotExecutable as exc:
        raise ValidationError(str(exc)) from exc

    return ExecPlanRead(
        artifact_id=artifact_id,
        command=plan.command,
        argv=plan.argv,
        workdir=plan.workdir,
        timeout_s=plan.timeout_s,
        confirm_token=plan.confirm_token,
        warning=EXEC_WARNING,
    )


@router.post("/artifacts/{artifact_id}/exec", response_model=ExecResultRead)
async def exec_artifact(
    artifact_id: int, payload: ExecRequest, session: SessionDep
) -> ExecResultRead:
    """Run it — only with a token naming this exact command (PRD F6.4).

    The two-step handshake is the whole safety property: nothing can start a
    process without having first asked what the process would be.
    """
    artifact = get_or_404(session, Artifact, artifact_id, "Artifact")
    try:
        plan = execute.plan(artifact)
    except execute.NotExecutable as exc:
        raise ValidationError(str(exc)) from exc

    if not payload.confirm_token or not execute.verify(plan, payload.confirm_token, artifact_id):
        raise ValidationError(
            "refusing to run without a valid confirmation token — fetch the exec "
            "plan first, show the user the command, and pass its token back"
        )

    result = await execute.execute(plan)
    return ExecResultRead(
        exit_code=result.exit_code,
        stdout=result.stdout,
        stderr=result.stderr,
        duration_ms=result.duration_ms,
        timed_out=result.timed_out,
    )
