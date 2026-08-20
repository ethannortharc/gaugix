"""Run, RunItem and Attempt (PRD §5, ARCHITECTURE §3/§5).

Runs are append-only records. Every state transition is committed immediately so
that killing the process never loses work, and everything a run needed is frozen
into it at plan time so later edits cannot rewrite history.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlmodel import Field, Index

from gaugix.domain import (
    AttemptStatus,
    CaseSnapshot,
    ExecutorSnapshot,
    ItemStatus,
    RunStatus,
    Usage,
)
from gaugix.models.base import TimestampMixin, dump_json, load_json


class Run(TimestampMixin, table=True):
    """One execution of {≥1 set} × {≥1 executor} with a frozen config snapshot."""

    __tablename__ = "run"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(default="")
    status: str = Field(default=str(RunStatus.pending), index=True)
    parent_run_id: int | None = Field(default=None, foreign_key="run.id", index=True)
    config_json: str = Field(default="{}")
    totals_json: str = Field(default="{}")
    is_baseline_for_json: str = Field(default="[]")
    error: str | None = Field(default=None)
    started_at: datetime | None = Field(default=None)
    finished_at: datetime | None = Field(default=None)

    @property
    def config(self) -> dict[str, Any]:
        value = load_json(self.config_json, {})
        return value if isinstance(value, dict) else {}

    @config.setter
    def config(self, value: dict[str, Any]) -> None:
        self.config_json = dump_json(value)

    @property
    def totals(self) -> dict[str, Any]:
        value = load_json(self.totals_json, {})
        return value if isinstance(value, dict) else {}

    @totals.setter
    def totals(self, value: dict[str, Any]) -> None:
        self.totals_json = dump_json(value)

    @property
    def is_baseline_for(self) -> list[int]:
        value = load_json(self.is_baseline_for_json, [])
        return [int(v) for v in value] if isinstance(value, list) else []

    @is_baseline_for.setter
    def is_baseline_for(self, value: list[int]) -> None:
        self.is_baseline_for_json = dump_json(sorted(set(value)))

    @property
    def executors(self) -> list[ExecutorSnapshot]:
        raw = self.config.get("executors", [])
        out: list[ExecutorSnapshot] = []
        for item in raw if isinstance(raw, list) else []:
            try:
                out.append(ExecutorSnapshot.model_validate(item))
            except Exception:
                continue
        return out

    @property
    def is_terminal(self) -> bool:
        return self.status in {
            RunStatus.completed,
            RunStatus.failed,
            RunStatus.canceled,
            RunStatus.interrupted,
        }

    @property
    def is_resumable(self) -> bool:
        """Canceled/interrupted/pending runs can be resumed (PRD F3.5)."""
        return self.status in {
            RunStatus.pending,
            RunStatus.canceled,
            RunStatus.interrupted,
            RunStatus.completed,
            RunStatus.failed,
        }


class RunItem(TimestampMixin, table=True):
    """One (case × executor) inside a run, with its frozen case snapshot."""

    __tablename__ = "run_item"
    __table_args__ = (
        Index("ix_run_item_run_lane", "run_id", "executor_key", "position"),
        Index("ix_run_item_run_status", "run_id", "status"),
    )

    id: int | None = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="run.id", index=True)
    set_id: int | None = Field(default=None, index=True)
    set_name: str = Field(default="")
    case_id: int | None = Field(default=None, index=True)
    #: The leaf branch and both forms of its ancestry are frozen at plan time.
    #: These are deliberately not foreign keys: deleting or reorganising the
    #: live set must not invalidate historical reports.
    node_id: int | None = Field(default=None, index=True)
    node_path_json: str = Field(default="[]")
    node_path_ids_json: str = Field(default="[]")
    executor_key: str = Field(default="", index=True)
    position: int = Field(default=0)
    case_snapshot_json: str = Field(default="{}")
    status: str = Field(default=str(ItemStatus.pending), index=True)
    verdict: bool | None = Field(default=None)
    score_value: float | None = Field(default=None)
    needs_human: bool = Field(default=False, index=True)
    current_attempt_id: int | None = Field(default=None)
    error: str | None = Field(default=None)

    @property
    def case_snapshot(self) -> CaseSnapshot:
        raw = load_json(self.case_snapshot_json, {})
        return CaseSnapshot.model_validate(raw)

    @case_snapshot.setter
    def case_snapshot(self, value: CaseSnapshot) -> None:
        self.case_snapshot_json = dump_json(value.model_dump(mode="json"))

    @property
    def title(self) -> str:
        raw = load_json(self.case_snapshot_json, {})
        return str(raw.get("title", "")) if isinstance(raw, dict) else ""

    @property
    def node_path(self) -> list[str]:
        value = load_json(self.node_path_json, [])
        return [str(part) for part in value] if isinstance(value, list) else []

    @node_path.setter
    def node_path(self, value: list[str]) -> None:
        self.node_path_json = dump_json(value)

    @property
    def node_path_ids(self) -> list[int]:
        value = load_json(self.node_path_ids_json, [])
        if not isinstance(value, list):
            return []
        return [part for part in value if isinstance(part, int) and not isinstance(part, bool)]

    @node_path_ids.setter
    def node_path_ids(self, value: list[int]) -> None:
        self.node_path_ids_json = dump_json(value)


class Attempt(TimestampMixin, table=True):
    """One actual invocation. Reruns append attempts; old ones are kept, superseded."""

    __tablename__ = "attempt"
    __table_args__ = (Index("ix_attempt_item_n", "run_item_id", "n"),)

    id: int | None = Field(default=None, primary_key=True)
    run_item_id: int = Field(foreign_key="run_item.id", index=True)
    n: int = Field(default=1)
    status: str = Field(default=str(AttemptStatus.ok))
    request_json: str = Field(default="{}")
    output_text: str = Field(default="")
    messages_json: str = Field(default="[]")
    prompt_tokens: int = Field(default=0)
    completion_tokens: int = Field(default=0)
    cost_usd: float | None = Field(default=None)
    latency_ms: int = Field(default=0)
    error: str | None = Field(default=None)
    error_kind: str | None = Field(default=None)
    retries: int = Field(default=0)
    superseded: bool = Field(default=False, index=True)
    purpose: str = Field(default="eval")

    @property
    def usage(self) -> Usage:
        return Usage(
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
            cost_usd=self.cost_usd,
            latency_ms=self.latency_ms,
        )

    @usage.setter
    def usage(self, value: Usage) -> None:
        self.prompt_tokens = value.prompt_tokens
        self.completion_tokens = value.completion_tokens
        self.cost_usd = value.cost_usd
        self.latency_ms = value.latency_ms

    @property
    def messages(self) -> list[dict[str, Any]]:
        value = load_json(self.messages_json, [])
        return value if isinstance(value, list) else []

    @messages.setter
    def messages(self, value: list[dict[str, Any]]) -> None:
        self.messages_json = dump_json(value)

    @property
    def request(self) -> dict[str, Any]:
        value = load_json(self.request_json, {})
        return value if isinstance(value, dict) else {}

    @request.setter
    def request(self, value: dict[str, Any]) -> None:
        self.request_json = dump_json(value)
