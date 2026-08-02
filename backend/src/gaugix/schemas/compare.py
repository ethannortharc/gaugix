"""DTOs for the comparison views (PRD F5.2–F5.4)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class BucketStats(BaseModel):
    """The same shape everywhere a group of items is summarised."""

    model_config = ConfigDict(extra="forbid")

    items: int
    scored: int
    passed: int
    failed: int
    unscored: int
    errors: int
    needs_human: int
    #: None, not 0, when nothing was scored — 0% reads as total failure.
    pass_rate: float | None
    mean_score: float | None
    mean_latency_ms: int | None
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float | None
    #: True when some call could not be priced, so `cost_usd` is a floor.
    cost_unknown: bool
    latency_ms: int


class CompareRunOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    name: str
    status: str
    created_at: datetime
    finished_at: datetime | None
    is_baseline_for: list[int]
    set_ids: list[int]
    totals: dict[str, Any]


class NamedRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    name: str


class CompareOptions(BaseModel):
    """Everything the comparison picker needs, in one call."""

    model_config = ConfigDict(extra="forbid")

    runs: list[CompareRunOption]
    sets: list[NamedRef]
    executors: list[str]


class DiffEntryRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: int | None
    title: str
    set_id: int | None
    set_name: str
    executor_key: str
    #: regressed | improved | unchanged | new | removed | unresolved
    kind: str
    baseline_item_id: int | None
    current_item_id: int | None
    baseline_verdict: bool | None
    current_verdict: bool | None
    baseline_status: str | None
    current_status: str | None
    baseline_score: float | None
    current_score: float | None
    score_delta: float | None
    note: str | None


class DiffExecutors(BaseModel):
    model_config = ConfigDict(extra="forbid")

    both: list[str]
    only_current: list[str]
    only_baseline: list[str]


class SideBySide(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current: float | None
    baseline: float | None


class PairedMetrics(BaseModel):
    """Both runs restricted to the (set, case, executor) identities they share.

    This is the only pair of numbers that can be subtracted from each other. The
    unpaired totals on `DiffRead` describe two different bodies of work.
    """

    model_config = ConfigDict(extra="forbid")

    items: int
    pass_rate: SideBySide
    mean_score: SideBySide


class SetCoverage(BaseModel):
    """Which baseline a set resolves to, and whether this diff covers it."""

    model_config = ConfigDict(extra="forbid")

    set_id: int
    set_name: str
    baseline_run_id: int | None
    baseline_run_name: str
    #: False when this set's baseline is a different run from the one diffed —
    #: its numbers are excluded rather than silently mixed in.
    included: bool
    reason: str | None = None


class CaseUniverse(BaseModel):
    """What each side of a diff actually ran, for one set.

    The paired delta already restricts the arithmetic to shared identities, so
    the numbers are sound without this. What this adds is the sentence a reader
    needs: "40% → 100%" means something very different when the second run was
    two of those five cases.
    """

    model_config = ConfigDict(extra="forbid")

    set_id: int
    set_name: str
    #: "2 of 5 cases", "all 5 cases", or "not in this run".
    current: str
    baseline: str
    current_partial: bool
    baseline_partial: bool
    #: None when either run predates coverage recording.
    same_universe: bool | None


class DiffRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: False when there is simply no baseline yet. "Nothing to compare against"
    #: is a normal state of the world, not a malformed request, so it comes back
    #: as a 200 with a reason rather than a 4xx the browser logs as an error.
    available: bool = True
    reason: str | None = None
    current_run_id: int
    baseline_run_id: int
    counts: dict[str, int]
    entries: list[DiffEntryRead]
    executors: DiffExecutors
    #: False when the two runs share no identity at all — no overall delta exists.
    comparable: bool = False
    paired: PairedMetrics = Field(
        default_factory=lambda: PairedMetrics(
            items=0,
            pass_rate=SideBySide(current=None, baseline=None),
            mean_score=SideBySide(current=None, baseline=None),
        )
    )
    #: Every set in the current run, with the baseline it points at.
    coverage: list[SetCoverage] = Field(default_factory=list)
    #: Per set, which cases each side actually ran. `same_universe` is None when
    #: a run predates coverage recording — unknown is not the same as mismatched.
    case_universes: list[CaseUniverse] = Field(default_factory=list)
    #: The subset of sets this diff actually covers.
    scoped_set_ids: list[int] = Field(default_factory=list)
    pass_rate: SideBySide
    mean_score: SideBySide


class LeaderboardRow(BucketStats):
    executor_key: str
    #: None when the executor scored nothing — it has no rank to claim.
    rank: int | None


class LeaderboardRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_ids: list[int]
    rows: list[LeaderboardRow]
    totals: BucketStats


class MatrixCell(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: int
    run_id: int
    status: str
    verdict: bool | None
    score_value: float | None
    needs_human: bool
    error: str | None


class MatrixRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    set_id: int | None
    set_name: str
    case_id: int | None
    title: str
    position: int
    cells: dict[str, MatrixCell]


class MatrixRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    executors: list[str]
    rows: list[MatrixRow]


class AggregateRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    set_id: int | None
    set_name: str
    cells: dict[str, BucketStats]
    totals: BucketStats


class AggregateMatrixRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    executors: list[str]
    rows: list[AggregateRow]
    totals: BucketStats
