"""Stable API shapes for task-aware evaluation summaries."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from gaugix.domain import EvaluationProfile


class MetricValueRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    value: float | None = None
    unit: str = "ratio"
    numerator: int | None = None
    denominator: int | None = None
    hint: str | None = None
    unavailable_reason: str | None = None


class ConfusionMatrixRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tp: int
    fp: int
    fn: int
    tn: int
    positive_label: str
    negative_label: str


class CategoryMetricRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str
    support: int
    predicted: int
    correct: int
    precision: float | None
    recall: float | None
    f1: float | None


class ThresholdPointRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    threshold: float
    precision: float | None
    recall: float | None
    false_positive_rate: float | None


class EvaluationCoverageRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: int
    valid: int
    execution_errors: int
    missing_truth: int = 0
    missing_prediction: int = 0


class EvaluationSliceRead(BaseModel):
    """One set × executor summary, optionally narrowed to a tree node."""

    model_config = ConfigDict(extra="forbid")

    set_id: int | None
    set_name: str
    executor_key: str
    node_id: int | None = None
    node_path: list[str] = Field(default_factory=list)
    profile: EvaluationProfile
    coverage: EvaluationCoverageRead
    metrics: list[MetricValueRead]
    confusion: ConfusionMatrixRead | None = None
    categories: list[CategoryMetricRead] = Field(default_factory=list)
    threshold_curve: list[ThresholdPointRead] = Field(default_factory=list)


class RunEvaluationRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: int
    slices: list[EvaluationSliceRead]
