"""Verdict and score aggregation (PRD F4.2, ARCHITECTURE §6).

These rules decide every number the product reports, so they are tested
exhaustively rather than by example.
"""

from __future__ import annotations

import pytest

from gaugix.domain import ScorerSpec
from gaugix.scoring.aggregate import ScoredScorer, aggregate, normalize_value, scale_bounds
from gaugix.scoring.assertions import ScoreResult


def scorer(
    index: int,
    scorer_type: str = "contains",
    required: bool = True,
    weight: float = 1.0,
    passed: bool | None = True,
    value: float | None = 100.0,
    resolved: bool = True,
    error: bool = False,
) -> ScoredScorer:
    spec = ScorerSpec.model_validate(
        {"type": scorer_type, "params": {}, "required": required, "weight": weight}
    )
    result = (
        ScoreResult(passed=passed, value=value, rationale="", error=error) if resolved else None
    )
    return ScoredScorer(index=index, spec=spec, result=result)


# -- verdict -------------------------------------------------------------------


def test_all_required_scorers_passing_is_a_pass():
    outcome = aggregate([scorer(0), scorer(1)])
    assert outcome.verdict is True
    assert outcome.failing == []


def test_one_failing_required_scorer_fails_the_item():
    outcome = aggregate([scorer(0), scorer(1, passed=False, value=0.0)])
    assert outcome.verdict is False
    assert outcome.failing == [1]


def test_a_failing_optional_scorer_does_not_fail_the_item():
    outcome = aggregate([scorer(0), scorer(1, required=False, passed=False, value=0.0)])
    assert outcome.verdict is True


def test_a_required_scorer_error_fails_the_item():
    """A required scorer that could not decide cannot be counted as a pass."""
    outcome = aggregate([scorer(0), scorer(1, passed=None, value=None, error=True)])
    assert outcome.verdict is False
    assert outcome.failing == [1]


def test_an_optional_scorer_error_does_not_fail_the_item():
    outcome = aggregate([scorer(0), scorer(1, required=False, passed=None, value=None, error=True)])
    assert outcome.verdict is True


def test_no_scorers_at_all_leaves_the_verdict_unknown():
    """ "Passed" would claim something nothing checked."""
    outcome = aggregate([])
    assert outcome.verdict is None
    assert outcome.score_value is None
    assert outcome.resolved_count == 0


def test_only_optional_scorers_leaves_the_verdict_unknown_but_scores_it():
    outcome = aggregate([scorer(0, required=False, value=80.0)])
    assert outcome.verdict is None
    assert outcome.score_value == 80.0


# -- unresolved human scorers --------------------------------------------------


def test_an_unresolved_human_scorer_flags_the_item_without_blocking_the_verdict():
    outcome = aggregate([scorer(0), scorer(1, scorer_type="human", resolved=False)])
    assert outcome.verdict is True, "the verdict is computed over resolved scorers only"
    assert outcome.needs_human is True


def test_a_resolved_human_scorer_participates_normally():
    outcome = aggregate([scorer(0), scorer(1, scorer_type="human", passed=False, value=0.0)])
    assert outcome.verdict is False
    assert outcome.needs_human is False


def test_only_an_unresolved_human_scorer_means_no_verdict_yet():
    outcome = aggregate([scorer(0, scorer_type="human", resolved=False)])
    assert outcome.verdict is None
    assert outcome.needs_human is True
    assert outcome.resolved_count == 0


# -- numeric score -------------------------------------------------------------


def test_score_is_the_weighted_mean():
    # (100×1 + 0×3) / 4 = 25
    outcome = aggregate(
        [scorer(0, weight=1, value=100.0), scorer(1, weight=3, passed=False, value=0.0)]
    )
    assert outcome.score_value == 25.0


def test_equal_weights_give_a_plain_mean():
    outcome = aggregate([scorer(0, value=100.0), scorer(1, value=50.0)])
    assert outcome.score_value == 75.0


def test_scorers_without_a_value_are_left_out_of_the_mean():
    outcome = aggregate([scorer(0, value=100.0), scorer(1, value=None)])
    assert outcome.score_value == 100.0


def test_all_zero_weights_fall_back_to_an_unweighted_mean():
    outcome = aggregate([scorer(0, weight=0, value=100.0), scorer(1, weight=0, value=0.0)])
    assert outcome.score_value == 50.0


def test_no_numeric_scorers_means_no_score():
    outcome = aggregate([scorer(0, value=None)])
    assert outcome.score_value is None
    assert outcome.verdict is True


# -- normalisation -------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "scale", "expected"),
    [
        (None, "1-5", None),
        (1, "1-5", 0.0),
        (3, "1-5", 50.0),
        (5, "1-5", 100.0),
        (4, "1-5", 75.0),
        (0, "binary", 0.0),
        (1, "binary", 100.0),
        (73, "0-100", 73.0),
        (73, None, 73.0),
        (1, "1-10", 0.0),
        (10, "1-10", 100.0),
        (150, "0-100", 100.0),
        (-5, "0-100", 0.0),
        # Any `low-high` scale is read off its own bounds. `1-7` used to fall
        # through to the percentage clamp and score a perfect 7 as 7 out of 100
        # — the same shape as the `0-1` bug, one unlisted scale later (D-066).
        (7, "1-7", 100.0),
        (1, "1-7", 0.0),
        (4, "1-7", 50.0),
        (10, "0-10", 100.0),
        (9, "1-7", 100.0),  # still clamped past the top
        (73, "percent", 73.0),
        (1, "0-1", 100.0),
        (0.5, "0-1", 50.0),
        (-1, "-1-1", 0.0),
        (0, "-1-1", 50.0),
        (1, "-1-1", 100.0),
    ],
)
def test_normalize_value(value, scale, expected):
    assert normalize_value(value, scale) == expected


@pytest.mark.parametrize("scale", ["likert", "A-F", "7-1", "grade", "1-"])
def test_a_scale_with_no_numeric_range_yields_no_number(scale):
    """Refusing beats guessing: a clamp here invents a plausible wrong score."""
    assert scale_bounds(scale) is None
    assert normalize_value(3, scale) is None


@pytest.mark.parametrize(
    ("scale", "expected"),
    [
        (None, (0.0, 100.0)),
        ("", (0.0, 100.0)),
        ("  ", (0.0, 100.0)),
        ("1-5", (1.0, 5.0)),
        ("1-7", (1.0, 7.0)),
        ("0.5-2.5", (0.5, 2.5)),
        ("-1-1", (-1.0, 1.0)),
        ("-1--0.5", (-1.0, -0.5)),
        (".5-2.5", (0.5, 2.5)),
        ("BINARY", (0.0, 1.0)),
        (" 1 - 10 ", (1.0, 10.0)),
    ],
)
def test_scale_bounds(scale, expected):
    assert scale_bounds(scale) == expected


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_values_never_become_plausible_scores(value):
    assert normalize_value(value, "1-5") is None
    assert normalize_value(value, None) is None
