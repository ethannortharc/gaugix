"""DTOs for one-off, non-persisted executor invocations."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from gaugix.domain import Message, Usage


class PlaygroundRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    executor_id: int
    messages: list[Message] = Field(min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)
    timeout_s: float = Field(default=120, ge=1, le=300)


class PlaygroundArtifactRead(BaseModel):
    kind: str
    filename: str
    mime: str


class PlaygroundResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    executor_key: str
    output_text: str = ""
    parsed_output: Any | None = None
    messages: list[dict[str, Any]] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    raw: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[PlaygroundArtifactRead] = Field(default_factory=list)
    error: str | None = None
    error_kind: str | None = None
