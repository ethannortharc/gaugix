"""Pure metric functions for extensible evaluation profiles.

Nothing here knows what a Guardrail is.  The binary classifier profile reads a
truth value, a predicted value and optional probability/category fields.  A
Guard model, spam detector or routing classifier all reduce to those facts.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass

from gaugix.domain import EvaluationProfile
from gaugix.schemas.evaluation import (
    CategoryMetricRead,
    ConfusionMatrixRead,
    EvaluationCoverageRead,
    MetricValueRead,
    ThresholdPointRead,
)


@dataclass(slots=True)
class Observation:
    item_id: int
    status: str
    verdict: bool | None
    truth: str | None = None
    prediction: str | None = None
    score: float | None = None
    truth_category: str | None = None
    predicted_category: str | None = None
    latency_ms: int | None = None


@dataclass(slots=True)
class MetricsResult:
    coverage: EvaluationCoverageRead
    metrics: list[MetricValueRead]
    confusion: ConfusionMatrixRead | None = None
    categories: list[CategoryMetricRead] | None = None
    threshold_curve: list[ThresholdPointRead] | None = None


def summarize(profile: EvaluationProfile, observations: list[Observation]) -> MetricsResult:
    if profile.kind == "binary_classification":
        return _binary(profile, observations)
    return _standard(observations)


def _standard(observations: list[Observation]) -> MetricsResult:
    scored = [row for row in observations if row.verdict is not None]
    passed = sum(row.verdict is True for row in scored)
    errors = sum(row.status == "error" for row in observations)
    latencies = _latencies(observations)
    return MetricsResult(
        coverage=EvaluationCoverageRead(
            items=len(observations),
            valid=len(scored),
            execution_errors=errors,
        ),
        metrics=[
            _ratio("pass_rate", "Pass rate", passed, len(scored)),
            _ratio("scored_coverage", "Scored coverage", len(scored), len(observations)),
            _ratio("execution_error_rate", "Execution error rate", errors, len(observations)),
            *_latency_metrics(latencies),
        ],
    )


def _binary(profile: EvaluationProfile, observations: list[Observation]) -> MetricsResult:
    positive = {_normal(value) for value in profile.positive_values}
    negative = {_normal(value) for value in profile.negative_values}
    errors = sum(row.status == "error" for row in observations)
    missing_truth = 0
    missing_prediction = 0
    valid: list[tuple[Observation, bool, bool]] = []

    for row in observations:
        truth = _classify(row.truth, positive, negative)
        prediction = _classify(row.prediction, positive, negative)
        if truth is None:
            missing_truth += 1
        if prediction is None:
            missing_prediction += 1
        if truth is not None and prediction is not None:
            valid.append((row, truth, prediction))

    tp = sum(truth and prediction for _, truth, prediction in valid)
    fp = sum(not truth and prediction for _, truth, prediction in valid)
    fn = sum(truth and not prediction for _, truth, prediction in valid)
    tn = sum(not truth and not prediction for _, truth, prediction in valid)
    predicted_positive = tp + fp

    category_rows = _categories(valid)
    scored: list[tuple[float | None, bool]] = [
        (row.score, truth) for row, truth, _ in valid if row.score is not None
    ]
    auprc = _average_precision(scored)
    ece = _ece(scored)

    score_reason = None
    if not scored:
        score_reason = "No valid item returned the configured probability score."

    metrics = [
        _ratio(
            "positive_rate",
            f"{profile.positive_label.capitalize()} rate",
            predicted_positive,
            len(valid),
        ),
        _ratio("precision", "Precision", tp, tp + fp),
        _ratio("recall", "Recall", tp, tp + fn),
        _f1_metric("f1", "F1", tp, fp, fn),
        _ratio("false_positive_rate", profile.false_positive_label, fp, fp + tn),
        _ratio("specificity", "Specificity", tn, tn + fp),
        _ratio("accuracy", "Accuracy", tp + tn, len(valid)),
        _ratio("valid_coverage", "Valid metric coverage", len(valid), len(observations)),
        MetricValueRead(
            key="auprc",
            label="AUPRC",
            value=auprc,
            numerator=len(scored) if scored else None,
            denominator=len(valid) if valid else None,
            hint="Average precision over items with a configured probability score.",
            unavailable_reason=score_reason,
        ),
        MetricValueRead(
            key="ece",
            label="ECE",
            value=ece,
            numerator=len(scored) if scored else None,
            denominator=len(valid) if valid else None,
            hint="Ten-bin expected calibration error; lower is better.",
            unavailable_reason=score_reason,
        ),
    ]

    if category_rows:
        correctly_attributed = sum(
            truth and prediction and row.truth_category == row.predicted_category
            for row, truth, prediction in valid
            if row.truth_category is not None
        )
        detected_with_category_truth = sum(
            truth and prediction
            for row, truth, prediction in valid
            if row.truth_category is not None
        )
        category_positive_support = sum(
            truth for row, truth, _ in valid if row.truth_category is not None
        )
        metrics.extend(
            [
                _ratio(
                    "category_attribution_accuracy",
                    "Category attribution accuracy",
                    correctly_attributed,
                    detected_with_category_truth,
                ),
                _ratio(
                    "end_to_end_category_recall",
                    "End-to-end category recall",
                    correctly_attributed,
                    category_positive_support,
                ),
                _mean_metric(
                    "macro_category_precision",
                    "Macro category precision",
                    [row.precision for row in category_rows],
                ),
                _mean_metric(
                    "macro_category_recall",
                    "Macro category recall",
                    [row.recall for row in category_rows],
                ),
                _mean_metric(
                    "macro_category_f1",
                    "Macro category F1",
                    [row.f1 for row in category_rows],
                ),
            ]
        )

    metrics.extend(_latency_metrics(_latencies(observations)))
    return MetricsResult(
        coverage=EvaluationCoverageRead(
            items=len(observations),
            valid=len(valid),
            execution_errors=errors,
            missing_truth=missing_truth,
            missing_prediction=missing_prediction,
        ),
        metrics=metrics,
        confusion=ConfusionMatrixRead(
            tp=tp,
            fp=fp,
            fn=fn,
            tn=tn,
            positive_label=profile.positive_label,
            negative_label=profile.negative_label,
        ),
        categories=category_rows,
        threshold_curve=_threshold_curve(scored),
    )


def _categories(valid: list[tuple[Observation, bool, bool]]) -> list[CategoryMetricRead]:
    # category -> (correct, predicted, support). A wrong attribution creates a
    # false positive for the predicted class and a false negative for the true.
    counts: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    for row, truth, prediction in valid:
        if truth and row.truth_category:
            counts[row.truth_category][2] += 1
        if prediction and row.predicted_category:
            counts[row.predicted_category][1] += 1
        if (
            truth
            and prediction
            and row.truth_category
            and row.truth_category == row.predicted_category
        ):
            counts[row.truth_category][0] += 1

    rows: list[CategoryMetricRead] = []
    for category in sorted(counts):
        correct, predicted, support = counts[category]
        precision = _safe_div(correct, predicted)
        recall = _safe_div(correct, support)
        f1 = _harmonic(precision, recall)
        rows.append(
            CategoryMetricRead(
                category=category,
                support=support,
                predicted=predicted,
                correct=correct,
                precision=precision,
                recall=recall,
                f1=f1,
            )
        )
    return rows


def _average_precision(scored: list[tuple[float | None, bool]]) -> float | None:
    rows = sorted(
        ((float(score), truth) for score, truth in scored if score is not None),
        key=lambda row: row[0],
        reverse=True,
    )
    positives = sum(truth for _, truth in rows)
    if not rows or positives == 0 or positives == len(rows):
        return None
    hits = 0
    precision_sum = 0.0
    for index, (_, truth) in enumerate(rows, start=1):
        if truth:
            hits += 1
            precision_sum += hits / index
    return precision_sum / positives


def _ece(scored: list[tuple[float | None, bool]], bins: int = 10) -> float | None:
    rows = [(float(score), truth) for score, truth in scored if score is not None]
    if not rows:
        return None
    total = len(rows)
    error = 0.0
    for index in range(bins):
        low = index / bins
        high = (index + 1) / bins
        bucket = [
            (score, truth)
            for score, truth in rows
            if (low <= score <= high if index == bins - 1 else low <= score < high)
        ]
        if not bucket:
            continue
        confidence = sum(score for score, _ in bucket) / len(bucket)
        frequency = sum(truth for _, truth in bucket) / len(bucket)
        error += len(bucket) / total * abs(frequency - confidence)
    return error


def _threshold_curve(scored: list[tuple[float | None, bool]]) -> list[ThresholdPointRead]:
    rows = [(float(score), truth) for score, truth in scored if score is not None]
    if not rows:
        return []
    thresholds = sorted({0.0, 1.0, *(score for score, _ in rows)}, reverse=True)
    if len(thresholds) > 101:
        step = (len(thresholds) - 1) / 100
        thresholds = [thresholds[round(i * step)] for i in range(101)]
    points = []
    for threshold in thresholds:
        tp = fp = fn = tn = 0
        for score, truth in rows:
            prediction = score >= threshold
            tp += int(truth and prediction)
            fp += int(not truth and prediction)
            fn += int(truth and not prediction)
            tn += int(not truth and not prediction)
        points.append(
            ThresholdPointRead(
                threshold=threshold,
                precision=_safe_div(tp, tp + fp),
                recall=_safe_div(tp, tp + fn),
                false_positive_rate=_safe_div(fp, fp + tn),
            )
        )
    return points


def _normal(value: str) -> str:
    return value.strip().casefold()


def _classify(value: str | None, positive: set[str], negative: set[str]) -> bool | None:
    if value is None:
        return None
    normal = _normal(value)
    if normal in positive:
        return True
    if normal in negative:
        return False
    return None


def _safe_div(numerator: int | float, denominator: int | float) -> float | None:
    return float(numerator) / float(denominator) if denominator else None


def _harmonic(left: float | None, right: float | None) -> float | None:
    if left is None or right is None or left + right == 0:
        return None
    return 2 * left * right / (left + right)


def _ratio(key: str, label: str, numerator: int, denominator: int) -> MetricValueRead:
    return MetricValueRead(
        key=key,
        label=label,
        value=_safe_div(numerator, denominator),
        numerator=numerator,
        denominator=denominator,
        unavailable_reason=None if denominator else "The denominator is zero.",
    )


def _f1_metric(key: str, label: str, tp: int, fp: int, fn: int) -> MetricValueRead:
    precision = _safe_div(tp, tp + fp)
    recall = _safe_div(tp, tp + fn)
    return MetricValueRead(
        key=key,
        label=label,
        value=_harmonic(precision, recall),
        numerator=2 * tp,
        denominator=2 * tp + fp + fn,
        unavailable_reason=None if 2 * tp + fp + fn else "No positive examples were resolved.",
    )


def _mean_metric(key: str, label: str, values: list[float | None]) -> MetricValueRead:
    resolved = [value for value in values if value is not None]
    return MetricValueRead(
        key=key,
        label=label,
        value=sum(resolved) / len(resolved) if resolved else None,
        numerator=len(resolved),
        denominator=len(values),
        unavailable_reason=None if resolved else "No categories could be resolved.",
    )


def _latencies(observations: list[Observation]) -> list[int]:
    return sorted(
        row.latency_ms for row in observations if row.latency_ms is not None and row.latency_ms >= 0
    )


def _latency_metrics(values: list[int]) -> list[MetricValueRead]:
    return [
        _latency_metric("latency_p50", "Latency p50", values, 0.50),
        _latency_metric("latency_p95", "Latency p95", values, 0.95),
        _latency_metric("latency_p99", "Latency p99", values, 0.99),
    ]


def _latency_metric(key: str, label: str, values: list[int], quantile: float) -> MetricValueRead:
    if not values:
        return MetricValueRead(
            key=key,
            label=label,
            unit="milliseconds",
            unavailable_reason="No completed attempt recorded latency.",
        )
    index = max(0, math.ceil(len(values) * quantile) - 1)
    return MetricValueRead(
        key=key,
        label=label,
        value=float(values[index]),
        unit="milliseconds",
        numerator=len(values),
        denominator=len(values),
    )
