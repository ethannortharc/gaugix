from __future__ import annotations

import pytest

from gaugix.domain import EvaluationProfile, EvaluationValueSource
from gaugix.evaluation.metrics import Observation, summarize


def profile() -> EvaluationProfile:
    return EvaluationProfile(
        kind="binary_classification",
        name="Safety classifier",
        truth=EvaluationValueSource(source="tag", key="label"),
        prediction=EvaluationValueSource(source="output_json", key="verdict"),
        score=EvaluationValueSource(source="output_json", key="unsafe_score"),
        category_truth=EvaluationValueSource(source="tag", key="category"),
        category_prediction=EvaluationValueSource(source="output_json", key="category"),
        positive_values=["unsafe", "blocked"],
        negative_values=["safe", "allowed"],
        positive_label="blocked",
        negative_label="allowed",
        false_positive_label="Over-refusal",
    )


def metric(result, key: str):
    return next(row for row in result.metrics if row.key == key)


def test_binary_profile_computes_quality_over_refusal_categories_and_calibration():
    rows = [
        Observation(
            1,
            "passed",
            True,
            truth="unsafe",
            prediction="blocked",
            score=0.9,
            truth_category="bias",
            predicted_category="bias",
            latency_ms=10,
        ),
        Observation(
            2,
            "failed",
            False,
            truth="unsafe",
            prediction="allowed",
            score=0.2,
            truth_category="crime",
            latency_ms=20,
        ),
        Observation(
            3,
            "failed",
            False,
            truth="safe",
            prediction="blocked",
            score=0.8,
            predicted_category="bias",
            latency_ms=30,
        ),
        Observation(
            4,
            "passed",
            True,
            truth="safe",
            prediction="allowed",
            score=0.1,
            latency_ms=40,
        ),
    ]

    result = summarize(profile(), rows)

    assert result.confusion is not None
    assert result.confusion.model_dump() | {} == {
        "tp": 1,
        "fp": 1,
        "fn": 1,
        "tn": 1,
        "positive_label": "blocked",
        "negative_label": "allowed",
    }
    assert metric(result, "precision").value == pytest.approx(0.5)
    assert metric(result, "recall").value == pytest.approx(0.5)
    assert metric(result, "false_positive_rate").label == "Over-refusal"
    assert metric(result, "false_positive_rate").value == pytest.approx(0.5)
    assert metric(result, "category_attribution_accuracy").value == pytest.approx(1.0)
    assert metric(result, "end_to_end_category_recall").value == pytest.approx(0.5)
    assert metric(result, "auprc").value == pytest.approx(5 / 6)
    assert metric(result, "ece").value is not None
    assert metric(result, "latency_p99").value == 40
    assert result.threshold_curve


def test_execution_errors_and_unknown_predictions_never_become_negative_predictions():
    rows = [
        Observation(1, "error", None, truth="unsafe", prediction=None),
        Observation(2, "passed", None, truth="unsafe", prediction="probe_error"),
        Observation(3, "passed", None, truth="safe", prediction="allowed"),
    ]

    result = summarize(profile(), rows)

    assert result.coverage.items == 3
    assert result.coverage.valid == 1
    assert result.coverage.execution_errors == 1
    assert result.coverage.missing_prediction == 2
    assert result.confusion is not None
    assert result.confusion.fn == 0
    assert result.confusion.tn == 1


def test_standard_profile_preserves_generic_pass_rate_semantics():
    rows = [
        Observation(1, "passed", True, latency_ms=8),
        Observation(2, "failed", False, latency_ms=12),
        Observation(3, "passed", None, latency_ms=10),
    ]

    result = summarize(EvaluationProfile.standard(), rows)

    assert result.confusion is None
    assert metric(result, "pass_rate").value == pytest.approx(0.5)
    assert metric(result, "scored_coverage").value == pytest.approx(2 / 3)
