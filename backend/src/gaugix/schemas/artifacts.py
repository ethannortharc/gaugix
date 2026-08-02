"""DTOs for artifacts (PRD F6)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ArtifactRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    attempt_id: int
    #: raw_output | code_block | workdir_file | capture
    kind: str
    filename: str
    mime: str
    size_bytes: int
    sha256: str
    language: str | None
    block_index: int | None
    #: Whether the viewer can show this as text rather than offering a download.
    textual: bool
    created_at: datetime


class ArtifactSide(BaseModel):
    """One pane of a side-by-side comparison (PRD F6.5)."""

    model_config = ConfigDict(extra="forbid")

    item_id: int
    run_id: int
    executor_key: str
    title: str
    status: str
    verdict: bool | None
    score_value: float | None
    output_text: str
    artifacts: list[ArtifactRead]


class ArtifactCompare(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sides: list[ArtifactSide]


class ExecPlanRead(BaseModel):
    """What running an artifact would do — shown before anything happens."""

    model_config = ConfigDict(extra="forbid")

    artifact_id: int
    command: str
    argv: list[str]
    workdir: str
    timeout_s: float
    #: Authorises exactly this command. Invalid after a server restart.
    confirm_token: str
    warning: str


class ExecRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm_token: str


class ExecResultRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool
