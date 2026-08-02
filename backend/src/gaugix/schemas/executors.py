"""DTOs for model profiles, harness profiles and executors (PRD F2)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from gaugix.domain import HarnessKind, Pricing, Provider


class ModelProfileCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    name: str = Field(min_length=1)
    provider: Provider
    model_id: str = Field(default="")
    base_url: str | None = None
    api_key_env: str | None = Field(
        default=None,
        description="Name of the env var holding the key — never the key itself",
    )
    params: dict[str, Any] = Field(default_factory=dict)
    pricing: Pricing | None = None


class ModelProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    name: str | None = Field(default=None, min_length=1)
    provider: Provider | None = None
    model_id: str | None = None
    base_url: str | None = None
    api_key_env: str | None = None
    params: dict[str, Any] | None = None
    pricing: Pricing | None = None
    archived: bool | None = None


class ModelProfileRead(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    id: int
    name: str
    provider: str
    model_id: str
    base_url: str | None
    api_key_env: str | None
    params: dict[str, Any]
    pricing: Pricing | None
    archived: bool
    key_present: bool = Field(
        default=False, description="Whether the credential this profile needs is set"
    )
    created_at: datetime
    updated_at: datetime


class HarnessProfileCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    kind: HarnessKind
    config: dict[str, Any] = Field(default_factory=dict)


class HarnessProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1)
    kind: HarnessKind | None = None
    config: dict[str, Any] | None = None
    archived: bool | None = None


class HarnessProfileRead(BaseModel):
    id: int
    name: str
    kind: str
    config: dict[str, Any]
    archived: bool
    created_at: datetime
    updated_at: datetime


class ExecutorCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    name: str | None = Field(
        default=None, description="Display key; defaults to `<model> @ <harness>`"
    )
    model_profile_id: int
    harness_profile_id: int
    overrides: dict[str, Any] = Field(default_factory=dict)


class ExecutorUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    name: str | None = Field(default=None, min_length=1)
    model_profile_id: int | None = None
    harness_profile_id: int | None = None
    overrides: dict[str, Any] | None = None
    archived: bool | None = None


class ExecutorRead(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    id: int
    name: str
    model_profile_id: int
    harness_profile_id: int
    model_name: str
    model_id: str
    provider: str
    harness_name: str
    harness_kind: str
    overrides: dict[str, Any]
    archived: bool
    run_count: int = 0
    created_at: datetime
    updated_at: datetime


class TestConnectionResult(BaseModel):
    """Outcome of the per-profile "test connection" probe (PRD F2.2)."""

    ok: bool
    message: str
    latency_ms: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cost_usd: float | None = None
    output_preview: str | None = None
    error_kind: str | None = None


class ProviderKeyStatus(BaseModel):
    provider: str
    env_var: str
    present: bool
    masked: str | None = None


class PricingEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    model_id: str
    input_per_1m: float = Field(ge=0)
    output_per_1m: float = Field(ge=0)
    #: Where the rates came from. A `manual` row is the user's and a pull from
    #: litellm never overwrites it; `litellm` rows are refreshable. Defaults to
    #: manual so a row saved before this field existed stays the user's.
    source: Literal["manual", "litellm"] = "manual"


class ModelCapabilitiesRead(BaseModel):
    """What a model accepts, so the form offers real controls instead of raw JSON."""

    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    model_id: str
    #: False when litellm has never heard of this model. Every flag below is then
    #: permissive — "we don't know" must not present as "not supported".
    known: bool
    supported: list[str]
    reasoning_effort: bool
    temperature: bool
    max_tokens: bool
    thinking: bool
    effort_levels: list[str]


class SettingsRead(BaseModel):
    """Everything the Settings page shows. Keys are status-only, never values."""

    providers: list[ProviderKeyStatus]
    pricing: list[PricingEntry]
    default_concurrency: int
    provider_concurrency: int
    default_judge_executor_id: int | None
    data_dir: str
    db_path: str
    version: str


class SettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pricing: list[PricingEntry] | None = None
    default_concurrency: int | None = Field(default=None, ge=1, le=64)
    default_judge_executor_id: int | None = None


class PricingPullRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    #: Which models to look up. None means every non-archived model profile.
    model_ids: list[str] | None = None
    #: Also refresh rows that came from litellm before. Manual rows are never touched.
    refresh: bool = False


class PricingPullResult(BaseModel):
    """What a pull actually managed to find — named, not merely counted."""

    model_config = ConfigDict(protected_namespaces=())

    added: list[str]
    updated: list[str]
    unchanged: list[str]
    not_found: list[str]
    settings: SettingsRead
