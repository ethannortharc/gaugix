"""Domain value objects shared by the engine, harnesses, scoring and API layers.

These are *snapshots*: immutable copies frozen into a run so that later edits to
cases, models or executors can never change what a past run means
(PRD §5, ARCHITECTURE §3 "Snapshot rules").

Table models live in `gaugix.models`, API DTOs in `gaugix.schemas`. This module is
deliberately free of both, so the scoring/harness/engine packages can depend on it
without dragging in SQLAlchemy or FastAPI.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Role(StrEnum):
    system = "system"
    user = "user"
    assistant = "assistant"


class Provider(StrEnum):
    anthropic = "anthropic"
    openai = "openai"
    gemini = "gemini"
    openai_compatible = "openai_compatible"
    fake = "fake"


class HarnessKind(StrEnum):
    direct = "direct"
    fake = "fake"
    cli = "cli"


class ScorerType(StrEnum):
    contains = "contains"
    not_contains = "not_contains"
    regex = "regex"
    json_schema = "json_schema"
    python = "python"
    llm_judge = "llm_judge"
    human = "human"


class EvaluationValueSource(BaseModel):
    """Where an evaluation profile reads one semantic value.

    Profiles deliberately describe *data*, not a product vertical.  A binary
    safety detector, a spam classifier, a routing model and a medical triage
    classifier can therefore use the same aggregation engine by pointing it at
    different case and output fields.
    """

    model_config = ConfigDict(extra="forbid")

    source: Literal["tag", "reference", "output_json"]
    key: str | None = None


class EvaluationProfile(BaseModel):
    """How a set's outcomes should be interpreted beyond pass/fail.

    ``standard`` is the existing Gaugix behaviour. ``binary_classification``
    adds confusion-matrix and calibration metrics without teaching the core
    about Guardrails; Guardrail detection is one UI preset of this generic
    profile.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["standard", "binary_classification"] = "standard"
    name: str = "Standard evaluation"
    description: str | None = None
    truth: EvaluationValueSource | None = None
    prediction: EvaluationValueSource | None = None
    score: EvaluationValueSource | None = None
    score_scale: Literal["0-1", "0-100"] = "0-1"
    category_truth: EvaluationValueSource | None = None
    category_prediction: EvaluationValueSource | None = None
    positive_values: list[str] = Field(default_factory=lambda: ["positive"])
    negative_values: list[str] = Field(default_factory=lambda: ["negative"])
    positive_label: str = "positive"
    negative_label: str = "negative"
    false_positive_label: str = "False positive rate"

    @classmethod
    def standard(cls) -> EvaluationProfile:
        return cls()


class ScoreSource(StrEnum):
    auto = "auto"
    judge = "judge"
    human = "human"


class RunStatus(StrEnum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    canceled = "canceled"
    interrupted = "interrupted"


class ItemStatus(StrEnum):
    pending = "pending"
    invoking = "invoking"
    scoring = "scoring"
    passed = "passed"
    failed = "failed"
    error = "error"
    skipped = "skipped"


#: Item statuses that represent finished work which resume must not redo.
TERMINAL_KEPT_STATUSES: frozenset[ItemStatus] = frozenset({ItemStatus.passed, ItemStatus.failed})


class AttemptStatus(StrEnum):
    ok = "ok"
    error = "error"


class Message(BaseModel):
    """One chat message in a case's `input` or a harness's returned transcript."""

    model_config = ConfigDict(extra="forbid")

    role: Role
    content: str

    def as_api_dict(self) -> dict[str, str]:
        return {"role": str(self.role), "content": self.content}


class ScorerSpec(BaseModel):
    """One scorer configuration (PRD Appendix A)."""

    model_config = ConfigDict(extra="forbid")

    type: ScorerType
    params: dict[str, Any] = Field(default_factory=dict)
    required: bool = True
    weight: float = 1.0

    def config_hash(self) -> str:
        """Stable hash over type+params — lets re-scores detect config changes."""
        payload = json.dumps(
            {"type": str(self.type), "params": self.params}, sort_keys=True, default=str
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


class Pricing(BaseModel):
    """Per-million-token USD rates used when litellm cannot price a model."""

    model_config = ConfigDict(extra="forbid")

    input_per_1m: float
    output_per_1m: float


class CaseSnapshot(BaseModel):
    """A case exactly as it existed when a run was planned."""

    model_config = ConfigDict(extra="forbid")

    case_id: int | None = None
    title: str
    input: list[Message]
    reference: str | None = None
    scoring: list[ScorerSpec] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    notes: str | None = None

    def messages_for_api(self) -> list[dict[str, str]]:
        return [m.as_api_dict() for m in self.input]

    def prompt_text(self) -> str:
        """Flatten the input into a single prompt string (CLI harness, fake keying)."""
        return "\n\n".join(f"[{m.role}]\n{m.content}" for m in self.input)

    def content_key(self) -> str:
        """Deterministic key over case content — seeds FakeHarness behaviour."""
        payload = json.dumps(
            {"title": self.title, "input": [m.as_api_dict() for m in self.input]},
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ModelSnapshot(BaseModel):
    """A model profile frozen into a run config."""

    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    model_profile_id: int | None = None
    name: str
    provider: Provider
    model_id: str
    base_url: str | None = None
    api_key_env: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    pricing: Pricing | None = None


class HarnessSnapshot(BaseModel):
    """A harness profile frozen into a run config."""

    model_config = ConfigDict(extra="forbid")

    harness_profile_id: int | None = None
    name: str
    kind: HarnessKind
    config: dict[str, Any] = Field(default_factory=dict)


class ExecutorSnapshot(BaseModel):
    """ModelProfile × Harness + overrides — the unit everything downstream binds to."""

    model_config = ConfigDict(extra="forbid")

    executor_id: int | None = None
    key: str
    model: ModelSnapshot
    harness: HarnessSnapshot
    overrides: dict[str, Any] = Field(default_factory=dict)

    def effective_params(self) -> dict[str, Any]:
        """Model generation params with executor-level overrides applied."""
        return {**self.model.params, **self.overrides}


class InvokeContext(BaseModel):
    """Per-invocation context handed to a harness."""

    model_config = ConfigDict(extra="forbid")

    run_id: int | None = None
    item_id: int | None = None
    attempt_n: int = 1
    #: 0-based retry counter *within* this attempt. `attempt_n + try_index` is the
    #: invocation ordinal, which is what failure injection keys off.
    try_index: int = 0
    harness_config: dict[str, Any] = Field(default_factory=dict)
    params: dict[str, Any] = Field(default_factory=dict)
    timeout_s: float | None = None
    workdir_root: str | None = None
    purpose: str = "eval"


class ArtifactIn(BaseModel):
    """An artifact a harness wants persisted (content is written by the store)."""

    model_config = ConfigDict(extra="forbid")

    kind: str
    filename: str
    mime: str = "text/plain"
    text: str | None = None
    data: bytes | None = None


class Usage(BaseModel):
    """Token/cost/latency accounting for one invocation (ARCHITECTURE §4)."""

    model_config = ConfigDict(extra="forbid")

    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float | None = None
    latency_ms: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class InvocationResult(BaseModel):
    """What every harness returns."""

    model_config = ConfigDict(extra="forbid")

    output_text: str
    messages: list[dict[str, Any]] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    artifacts: list[ArtifactIn] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class HarnessError(Exception):
    """Invocation failed. `retryable` drives the runner's retry wrapper."""

    def __init__(self, message: str, *, retryable: bool = False, kind: str = "provider_error"):
        super().__init__(message)
        self.message = message
        self.retryable = retryable
        self.kind = kind
        #: Retries actually spent before giving up — set by the runner, not the harness.
        self.retries = 0
