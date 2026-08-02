"""ModelProfile, HarnessProfile and Executor (PRD §5, F2).

An Executor is ModelProfile × Harness + overrides — the unit every run, result and
comparison binds to. Executors that have runs are archived rather than deleted, so
past runs never lose the thing they point at.
"""

from __future__ import annotations

from typing import Any

from sqlmodel import Field

from gaugix.domain import (
    ExecutorSnapshot,
    HarnessKind,
    HarnessSnapshot,
    ModelSnapshot,
    Pricing,
    Provider,
)
from gaugix.models.base import TimestampMixin, dump_json, load_json


class ModelProfile(TimestampMixin, table=True):
    """A callable model: provider + model id + generation params."""

    __tablename__ = "model_profile"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    provider: str = Field(default=str(Provider.fake))
    model_id: str = Field(default="")
    base_url: str | None = Field(default=None)
    api_key_env: str | None = Field(default=None)
    params_json: str = Field(default="{}")
    pricing_json: str | None = Field(default=None)
    archived: bool = Field(default=False, index=True)

    @property
    def params(self) -> dict[str, Any]:
        value = load_json(self.params_json, {})
        return value if isinstance(value, dict) else {}

    @params.setter
    def params(self, value: dict[str, Any]) -> None:
        self.params_json = dump_json(value)

    @property
    def pricing(self) -> Pricing | None:
        raw = load_json(self.pricing_json, None)
        if not isinstance(raw, dict):
            return None
        try:
            return Pricing.model_validate(raw)
        except Exception:
            return None

    @pricing.setter
    def pricing(self, value: Pricing | None) -> None:
        self.pricing_json = None if value is None else dump_json(value.model_dump())

    def to_snapshot(self) -> ModelSnapshot:
        return ModelSnapshot(
            model_profile_id=self.id,
            name=self.name,
            provider=Provider(self.provider),
            model_id=self.model_id,
            base_url=self.base_url,
            api_key_env=self.api_key_env,
            params=self.params,
            pricing=self.pricing,
        )


class HarnessProfile(TimestampMixin, table=True):
    """How a model is invoked: direct API, the fake simulator, or a CLI agent."""

    __tablename__ = "harness_profile"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    kind: str = Field(default=str(HarnessKind.fake))
    config_json: str = Field(default="{}")
    archived: bool = Field(default=False, index=True)

    @property
    def config(self) -> dict[str, Any]:
        value = load_json(self.config_json, {})
        return value if isinstance(value, dict) else {}

    @config.setter
    def config(self, value: dict[str, Any]) -> None:
        self.config_json = dump_json(value)

    def to_snapshot(self) -> HarnessSnapshot:
        return HarnessSnapshot(
            harness_profile_id=self.id,
            name=self.name,
            kind=HarnessKind(self.kind),
            config=self.config,
        )


class Executor(TimestampMixin, table=True):
    """ModelProfile × Harness + overrides. `name` is the display key, e.g. `haiku @ direct`."""

    __tablename__ = "executor"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    model_profile_id: int = Field(foreign_key="model_profile.id", index=True)
    harness_profile_id: int = Field(foreign_key="harness_profile.id", index=True)
    overrides_json: str = Field(default="{}")
    archived: bool = Field(default=False, index=True)

    @property
    def overrides(self) -> dict[str, Any]:
        value = load_json(self.overrides_json, {})
        return value if isinstance(value, dict) else {}

    @overrides.setter
    def overrides(self, value: dict[str, Any]) -> None:
        self.overrides_json = dump_json(value)

    def to_snapshot(self, model: ModelProfile, harness: HarnessProfile) -> ExecutorSnapshot:
        return ExecutorSnapshot(
            executor_id=self.id,
            key=self.name,
            model=model.to_snapshot(),
            harness=harness.to_snapshot(),
            overrides=self.overrides,
        )


def default_executor_name(model_name: str, harness_name: str) -> str:
    """The `sonnet-4.5 @ direct` display key from PRD §5."""
    return f"{model_name} @ {harness_name}"
