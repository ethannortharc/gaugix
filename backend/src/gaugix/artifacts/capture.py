"""Turning one attempt's output into artifacts (PRD F6.1).

Called by the runner after an attempt succeeds. Three sources, in order:

1. the raw output, always — the transcript is the primary record;
2. every fenced code block in it, as a typed file;
3. whatever the harness collected itself (the CLI harness's working directory).

The whole thing is best-effort at the call site: artifacts are a convenience
layered over the output, and the output is already safe in the database. A disk
problem here must never turn a completed attempt into a failed one.
"""

from __future__ import annotations

from sqlmodel import Session

from gaugix.artifacts import store
from gaugix.artifacts.extract import extract_code_blocks
from gaugix.domain import ArtifactIn
from gaugix.models.artifacts import Artifact

RAW_OUTPUT_FILENAME = "output.md"

#: Above this, storing every fenced block stops being useful and starts being a
#: way to fill a disk from a runaway generation.
MAX_CODE_BLOCKS = 40


def capture_attempt(
    session: Session,
    *,
    run_id: int,
    item_id: int,
    attempt_id: int,
    attempt_n: int,
    output_text: str,
    harness_artifacts: list[ArtifactIn] | None = None,
) -> list[Artifact]:
    """Persist the artifacts for one attempt. Caller commits."""
    rows: list[Artifact] = []

    def write(**kwargs: object) -> None:
        stored = store.write_artifact(
            run_id=run_id,
            item_id=item_id,
            attempt_n=attempt_n,
            **kwargs,  # type: ignore[arg-type]
        )
        rows.append(store.persist(session, attempt_id, stored))

    if output_text:
        write(
            filename=RAW_OUTPUT_FILENAME,
            content=output_text.encode("utf-8"),
            kind="raw_output",
            mime="text/markdown",
        )

        for block in extract_code_blocks(output_text)[:MAX_CODE_BLOCKS]:
            write(
                filename=block.filename,
                content=block.content.encode("utf-8"),
                kind="code_block",
                mime=block.mime,
                language=block.language,
                block_index=block.index,
            )

    for artifact in harness_artifacts or []:
        content = artifact.data
        if content is None:
            content = (artifact.text or "").encode("utf-8")
        write(
            filename=artifact.filename,
            content=content,
            kind=artifact.kind,
            mime=artifact.mime,
        )

    return rows
