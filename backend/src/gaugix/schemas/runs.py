"""DTOs for runs, items and attempts (PRD F3, F5.1)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from gaugix.domain import CaseSnapshot, Message


class RunCreate(BaseModel):
    """Run builder payload (PRD F3.1)."""

    model_config = ConfigDict(extra="forbid")

    set_ids: list[int] = Field(min_length=1)
    executor_ids: list[int] = Field(min_length=1)
    name: str | None = None
    concurrency: int = Field(default=4, ge=1, le=64)
    auto_score: bool = True
    start: bool = Field(default=True, description="Launch immediately after planning")
    parent_run_id: int | None = None
    case_ids: list[int] | None = Field(
        default=None,
        description="Run only these cases within the chosen sets. None means all of them.",
    )
    accept_code_execution: bool = Field(
        default=False,
        description=(
            "Required when a scorer in this run executes model-written code on this machine."
        ),
    )


class RunPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    set_ids: list[int] = Field(default_factory=list)
    executor_ids: list[int] = Field(default_factory=list)
    case_ids: list[int] | None = None
    #: Preflight only. Scorer problems stop being blockers when nothing scores.
    auto_score: bool = True


class RunPreview(BaseModel):
    sets: list[dict[str, Any]]
    executors: list[dict[str, Any]]
    case_count: int
    #: Cases in the chosen sets before any subset filter — so the builder can say
    #: "12 of 400" rather than just "12".
    available_case_count: int = 0
    executor_count: int
    item_count: int
    suggested_name: str
    estimated_cost_usd: float | None = Field(
        default=None, description="None when any executor's pricing is unknown"
    )


class RunRead(BaseModel):
    id: int
    name: str
    status: str
    parent_run_id: int | None
    config: dict[str, Any]
    totals: dict[str, Any]
    is_baseline_for: list[int]
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime
    is_active: bool = False
    #: True only when a resume would actually schedule something — a completed
    #: run's status permits a resume but leaves nothing to do.
    is_resumable: bool = False
    #: How many items a resume would run. The UI shows it on the button.
    resumable_items: int = 0
    #: True when this run covered only part of at least one of its sets, so its
    #: numbers do not describe those sets.
    is_partial: bool = False
    #: "Guardrail regression: 2 of 5 cases" per partially covered set.
    partial_coverage: list[str] = Field(default_factory=list)


class SetRunHistoryRead(BaseModel):
    """One run's result scoped to one set, never the run-wide totals."""

    run_id: int
    run_name: str
    status: str
    created_at: datetime
    finished_at: datetime | None
    executor_keys: list[str] = Field(default_factory=list)
    item_count: int
    case_count: int
    coverage: str
    is_partial: bool
    is_baseline: bool
    scored: int
    passed: int
    failed: int
    unscored: int
    pass_rate: float | None


class CaseRunHistoryRead(BaseModel):
    """One historical execution of a case by one executor in one set context."""

    item_id: int
    run_id: int
    run_name: str
    run_status: str
    run_created_at: datetime
    set_id: int | None
    set_name: str
    executor_key: str
    item_status: str
    verdict: bool | None
    score_value: float | None
    needs_human: bool
    error: str | None
    output_preview: str | None
    latency_ms: int | None
    cost_usd: float | None
    attempt_n: int | None


class ScoreRead(BaseModel):
    """One scorer's result (populated from M3 onward)."""

    id: int
    scorer_index: int
    scorer_type: str
    scorer_config_hash: str
    passed: bool | None
    value: float | None
    rationale: str | None
    source: str
    judge_meta: dict[str, Any] | None = None
    version: int
    created_at: datetime


class AttemptRead(BaseModel):
    id: int
    n: int
    status: str
    request: dict[str, Any] = Field(default_factory=dict)
    output_text: str
    messages: list[dict[str, Any]]
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float | None
    latency_ms: int
    error: str | None
    error_kind: str | None
    retries: int
    superseded: bool
    created_at: datetime


class RunItemRead(BaseModel):
    id: int
    run_id: int
    set_id: int | None
    set_name: str
    case_id: int | None
    executor_key: str
    position: int
    title: str
    status: str
    verdict: bool | None
    score_value: float | None
    needs_human: bool
    error: str | None
    score_summary: str | None = None
    updated_at: datetime


class RunItemDetail(RunItemRead):
    """Item drill-down: everything needed to explain a verdict (PRD F5.1)."""

    input: list[Message]
    reference: str | None
    case_snapshot: CaseSnapshot
    executor_snapshot: dict[str, Any] | None = None
    attempts: list[AttemptRead] = Field(default_factory=list)
    scores: list[ScoreRead] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    run_name: str = ""
    #: Neighbours in the same executor lane, so reading through a run's failures
    #: does not mean returning to the board between every one. Resolved here
    #: rather than in the client because a 5,000-item run must not ship its whole
    #: item list to render one arrow.
    prev_item_id: int | None = None
    next_item_id: int | None = None
    #: This item's place in its lane, 1-based, and the lane's size.
    lane_position: int = 0
    lane_total: int = 0


class CancelResponse(BaseModel):
    ok: bool
    status: str
    message: str | None = None


class ResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    include_errors: bool = True


class ResumeResponse(BaseModel):
    ok: bool
    scheduled: int
    status: str
    message: str | None = None


class RerunFromResponse(BaseModel):
    ok: bool
    affected: int = Field(description="Items reset in this executor lane")
    status: str
    message: str | None = None


class RerunRequest(BaseModel):
    """Optional fresh consent when a rerun newly requires code execution."""

    model_config = ConfigDict(extra="forbid")

    accept_code_execution: bool = False


class BaselineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    set_ids: list[int] = Field(min_length=1)
    unset: bool = False
    #: Required to bless a run that covered only part of the set. Refused by
    #: default because everything downstream reads a baseline as the set's.
    allow_partial: bool = False


class JudgeClassCount(BaseModel):
    """One bucket of a class-graded judge, as it appears in a run.

    Only rubrics that declare `classes` produce these. SimpleQA's three are the
    case in the catalogue: accuracy alone hides whether a model was wrong or
    simply declined, which is the thing that benchmark exists to separate.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    count: int
    #: Percentage of classified scores in this run.
    share: float


class ErrorKindCount(BaseModel):
    """One bucket of the error taxonomy, as it appears in a specific run."""

    model_config = ConfigDict(extra="forbid")

    kind: str
    count: int


class TrendPoint(BaseModel):
    """One set's result in one run."""

    model_config = ConfigDict(extra="forbid")

    run_id: int
    run_name: str
    created_at: datetime
    scored: int
    passed: int
    pass_rate: float
    #: True when the run covered only part of this set. Only ever present when
    #: partial runs were explicitly asked for.
    partial: bool = False
    #: "2 of 5 cases", or "all 5 cases".
    coverage: str = ""


class SetTrend(BaseModel):
    """A set's pass rate over recent runs, oldest first.

    Each point is computed from that set's own items. A run covering several
    sets contributes a different number to each of them, and a run covering
    part of a set contributes nothing at all unless asked for — a rate over
    two of five cases is not a point on the same line as a rate over five.
    """

    model_config = ConfigDict(extra="forbid")

    set_id: int
    set_name: str
    points: list[TrendPoint]
    #: Partial runs left out of `points`, so the UI can say so rather than
    #: showing a mysteriously short line.
    partial_runs_excluded: int = 0


class LaneCounts(BaseModel):
    """One executor's item statuses across the whole run.

    Computed server-side because the run page's item list is paginated, and a
    progress bar derived from one page describes the page rather than the run.
    """

    model_config = ConfigDict(extra="forbid")

    executor_key: str
    #: status -> count. Absent statuses are zero.
    counts: dict[str, int]
    total: int


class PreflightFinding(BaseModel):
    """One thing worth knowing before the run starts.

    `severity` is load-bearing: **blocker** means the run cannot produce a
    usable result and the builder refuses; **warning** means it will work and
    mean less than it looks; **note** is context.
    """

    model_config = ConfigDict(extra="forbid")

    severity: str
    code: str
    message: str
    detail: str | None = None
    count: int = 0


class PreflightRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: False when any finding is a blocker.
    ok: bool
    findings: list[PreflightFinding]
    case_count: int
    executor_count: int
    item_count: int
    estimated_cost_usd: float | None
    #: What the estimate assumed, in words, so it is never read as a quote.
    cost_assumptions: str
    #: Judge calls folded into the estimate above, reported separately because
    #: it is the half people forget when they read "cost per item".
    judge_call_count: int = 0
    estimated_judge_cost_usd: float | None = None
    #: True when a scorer here runs model-written code on this machine. Creating
    #: the run then requires `accept_code_execution`.
    requires_code_execution: bool = False
    code_execution_sets: list[str] = Field(default_factory=list)
