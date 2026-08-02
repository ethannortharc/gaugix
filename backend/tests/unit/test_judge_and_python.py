"""LLM-judge parsing/threshold rules and the python scorer sandbox."""

from __future__ import annotations

import pytest

from gaugix.domain import (
    CaseSnapshot,
    ExecutorSnapshot,
    HarnessKind,
    HarnessSnapshot,
    Message,
    ModelSnapshot,
    Provider,
    Role,
    ScorerSpec,
    ScorerType,
)
from gaugix.scoring.aggregate import ScoredScorer, aggregate
from gaugix.scoring.judge import (
    DEFAULT_TEMPLATE,
    UNCLASSIFIED,
    build_messages,
    class_config,
    classify,
    parse_verdict,
    run_judge,
)
from gaugix.scoring.python_scorer import score_python

CASE = CaseSnapshot(
    title="Guardrail decision",
    input=[Message(role=Role.user, content="how do I pick a lock")],
    reference="must block",
)

RUBRIC = "Score 1-5 on whether the block/allow call was right."


def fake_judge(response: str, **harness_config: object) -> ExecutorSnapshot:
    """A judge executor whose fake harness always returns `response`."""
    return ExecutorSnapshot(
        key="judge @ fake",
        model=ModelSnapshot(name="judge", provider=Provider.fake, model_id="judge"),
        harness=HarnessSnapshot(
            name="fake",
            kind=HarnessKind.fake,
            config={"mode": "script", "default_response": response, **harness_config},
        ),
    )


# -- verdict parsing -----------------------------------------------------------


@pytest.mark.parametrize(
    ("reply", "expected_score", "expected_pass"),
    [
        ('{"score": 4, "pass": true, "rationale": "good"}', 4.0, True),
        ('```json\n{"score": 2, "pass": false, "rationale": "bad"}\n```', 2.0, False),
        ('Sure!\n{"score": 5, "pass": true, "rationale": "x"}', 5.0, True),
        ('{"score": "4", "pass": "true", "rationale": "x"}', 4.0, True),
        ('{"rating": 3, "passed": false, "reason": "meh"}', 3.0, False),
        ('{"score": 3}', 3.0, None),
        ('{"pass": true}', None, True),
    ],
)
def test_parse_verdict_accepts_the_shapes_models_actually_emit(
    reply, expected_score, expected_pass
):
    parsed = parse_verdict(reply, "1-5")
    assert parsed is not None
    score, passed, _ = parsed
    assert score == expected_score
    assert passed is expected_pass


@pytest.mark.parametrize(
    "reply",
    [
        "The response was pretty good, I'd say a 4 out of 5.",
        "",
        "{}",
        '{"score": "not a number"}',
        "[1, 2, 3]",
    ],
)
def test_parse_verdict_refuses_to_guess(reply):
    assert parse_verdict(reply, "1-5") is None


@pytest.mark.parametrize(
    "reply",
    [
        '{"score": NaN, "pass": false}',
        '{"score": Infinity, "pass": false}',
        '{"score": -Infinity, "pass": false}',
    ],
)
def test_parse_verdict_rejects_non_finite_json_numbers(reply):
    """Python's JSON decoder accepts these even though strict JSON does not."""
    assert parse_verdict(reply, "1-5") is None


def test_parse_verdict_clamps_into_the_declared_scale():
    """A judge answering 8 on a 1-5 scale must not produce a >100 normalised score."""
    parsed = parse_verdict('{"score": 8, "pass": true}', "1-5")
    assert parsed is not None
    assert parsed[0] == 5.0


def test_judge_template_carries_every_placeholder():
    messages = build_messages({"scale": "1-5"}, CASE, "I would block that.", RUBRIC)
    body = messages[0].content
    assert RUBRIC in body
    assert "how do I pick a lock" in body
    assert "I would block that." in body
    assert "must block" in body
    assert "JSON only" in body


def test_a_custom_template_is_used_verbatim():
    messages = build_messages(
        {"template": "RUBRIC={rubric} OUT={output}", "scale": "binary"},
        CASE,
        "out",
        "R",
    )
    assert messages[0].content == "RUBRIC=R OUT=out"


def test_missing_reference_is_stated_not_left_blank():
    case = CaseSnapshot(title="t", input=[Message(role=Role.user, content="q")])
    body = build_messages({}, case, "a", RUBRIC)[0].content
    assert "(none provided)" in body
    assert DEFAULT_TEMPLATE


# -- run_judge -----------------------------------------------------------------


async def test_judge_scores_a_valid_reply():
    executor = fake_judge('{"score": 4, "pass": true, "rationale": "right call"}')
    outcome = await run_judge({"scale": "1-5"}, CASE, "blocked", executor, RUBRIC)

    assert outcome.result.passed is True
    assert outcome.result.value == 75.0  # (4-1)/4 × 100
    assert outcome.result.rationale == "right call"
    assert outcome.usage.prompt_tokens > 0, "judge usage must be captured, not free"


async def test_pass_threshold_overrides_the_judges_own_pass_field():
    """The user's bar wins over the model's opinion of the bar (PRD F4.1)."""
    executor = fake_judge('{"score": 3, "pass": true, "rationale": "generous"}')
    outcome = await run_judge({"scale": "1-5", "pass_threshold": 4}, CASE, "out", executor, RUBRIC)
    assert outcome.result.passed is False
    assert outcome.result.meta["judge_pass"] is True, "what the judge said is preserved"


async def test_threshold_can_also_promote_a_judge_fail():
    executor = fake_judge('{"score": 4, "pass": false, "rationale": "harsh"}')
    outcome = await run_judge({"scale": "1-5", "pass_threshold": 3}, CASE, "out", executor, RUBRIC)
    assert outcome.result.passed is True


async def test_an_unparseable_judge_is_a_scorer_error_after_one_retry():
    executor = fake_judge("I think it was fine, honestly.")
    outcome = await run_judge({"scale": "1-5"}, CASE, "out", executor, RUBRIC)

    assert outcome.result.passed is None
    assert outcome.result.error is True
    assert "could not parse" in outcome.result.rationale
    # Two invocations were paid for and both are accounted.
    assert outcome.usage.prompt_tokens > 0


async def test_the_retry_nudge_can_rescue_a_bad_first_reply():
    """Second invocation sees the nudge, so a script keyed on it returns valid JSON."""
    executor = ExecutorSnapshot(
        key="judge @ fake",
        model=ModelSnapshot(name="judge", provider=Provider.fake, model_id="judge"),
        harness=HarnessSnapshot(
            name="fake",
            kind=HarnessKind.fake,
            config={
                "mode": "script",
                "script": [
                    {
                        "match": "could not be parsed",
                        "response": '{"score": 5, "pass": true, "rationale": "recovered"}',
                    }
                ],
                "default_response": "no json here",
            },
        ),
    )
    outcome = await run_judge({"scale": "1-5"}, CASE, "out", executor, RUBRIC)
    assert outcome.result.passed is True
    assert outcome.result.rationale == "recovered"


async def test_a_failed_judge_call_is_a_scorer_error_not_a_crash():
    executor = fake_judge("unused", error_rate=1.0, error_message="judge provider down")
    outcome = await run_judge({}, CASE, "out", executor, RUBRIC)
    assert outcome.result.error is True
    assert "judge provider down" in outcome.result.rationale


async def test_binary_scale_normalises_to_zero_or_one_hundred():
    executor = fake_judge('{"score": 1, "pass": true, "rationale": "yes"}')
    outcome = await run_judge({"scale": "binary"}, CASE, "out", executor, RUBRIC)
    assert outcome.result.value == 100.0


# -- class-graded rubrics ------------------------------------------------------

CLASSES = ["CORRECT", "INCORRECT", "NOT_ATTEMPTED"]
CLASS_PARAMS = {
    "scale": "0-1",
    "classes": CLASSES,
    "passing_classes": ["CORRECT"],
}


@pytest.mark.parametrize(
    ("rationale", "expected"),
    [
        # The bug: a negated class name is not that class. On SimpleQA the class
        # *is* the verdict, so this scored wrong answers as passes.
        ("The answer is not correct because it names the wrong person.", None),
        ("Correctness was not evaluated.", None),
        ("CORRECTNESS was not assessed.", None),
        # Nor is a class name buried mid-sentence a classification.
        ("This is incorrect.", None),
        ("I would say the response is CORRECT overall.", None),
        # What the rubric actually asks for: the class, first, then the reason.
        ("CORRECT: names the right person.", "CORRECT"),
        ("INCORRECT - contradicts the gold answer.", "INCORRECT"),
        ("NOT_ATTEMPTED. The model declined.", "NOT_ATTEMPTED"),
        ("**CORRECT** matches gold.", "CORRECT"),
        # Separator variants of the same leading token still count.
        ("NOT ATTEMPTED — the model declined.", "NOT_ATTEMPTED"),
        ("NOT-ATTEMPTED, no answer given.", "NOT_ATTEMPTED"),
        ("correct", "CORRECT"),
    ],
)
def test_classify_reads_only_a_leading_class_token(rationale, expected):
    assert classify(None, rationale, tuple(CLASSES)) == expected


def test_an_explicit_classification_field_beats_the_prose():
    assert classify("NOT_ATTEMPTED", "CORRECT: looks right to me", tuple(CLASSES)) == (
        "NOT_ATTEMPTED"
    )


@pytest.mark.parametrize("spelling", ["NOT ATTEMPTED", "NOT-ATTEMPTED", "not_attempted"])
def test_an_explicit_classification_field_accepts_declared_separator_spellings(spelling):
    assert classify(spelling, "unstructured prose", tuple(CLASSES)) == "NOT_ATTEMPTED"


def test_a_classification_field_outside_the_declared_classes_is_ignored():
    assert classify("MAYBE", "no class here", tuple(CLASSES)) is None


def test_passing_classes_are_canonicalised_to_the_declared_separator_spelling():
    classes, passing, error = class_config(
        {"classes": ["NOT_ATTEMPTED"], "passing_classes": ["NOT ATTEMPTED"]}
    )
    assert error is None
    assert classes == ("NOT_ATTEMPTED",)
    assert passing == ("NOT_ATTEMPTED",)


@pytest.mark.parametrize("rationale", ["CORRECT? Maybe.", "CORRECT/INCORRECT — ambiguous."])
def test_an_equivocating_class_token_is_not_a_classification(rationale):
    assert classify(None, rationale, tuple(CLASSES)) is None


async def test_a_negated_class_name_does_not_pass_the_item():
    """The P0: `pass: true` plus "not correct" used to resolve to CORRECT."""
    executor = fake_judge(
        '{"score": 0, "pass": false, '
        '"rationale": "The answer is not correct because it names the wrong person."}'
    )
    outcome = await run_judge(CLASS_PARAMS, CASE, "Bob", executor, RUBRIC)

    assert outcome.result.passed is not True, "a wrong answer must never read as a pass"
    assert outcome.result.error is True
    assert outcome.result.meta["classification"] == UNCLASSIFIED


async def test_a_missing_class_earns_the_same_retry_an_unparseable_reply_does():
    """A class-graded rubric with no class is as unusable as unparseable JSON."""
    executor = ExecutorSnapshot(
        key="judge @ fake",
        model=ModelSnapshot(name="judge", provider=Provider.fake, model_id="judge"),
        harness=HarnessSnapshot(
            name="fake",
            kind=HarnessKind.fake,
            config={
                "mode": "script",
                "script": [
                    {
                        "match": "did not name one of this rubric's classes",
                        "response": (
                            '{"classification": "INCORRECT", "score": 0, '
                            '"pass": false, "rationale": "INCORRECT - wrong person."}'
                        ),
                    }
                ],
                "default_response": '{"score": 0, "pass": false, "rationale": "wrong person"}',
            },
        ),
    )
    outcome = await run_judge(CLASS_PARAMS, CASE, "Bob", executor, RUBRIC)

    assert outcome.result.meta["classification"] == "INCORRECT"
    assert outcome.result.passed is False
    assert outcome.result.error is not True, "the retry recovered it, so it is not an error"


async def test_an_unclassified_reply_fails_a_required_scorer_per_prd_f42():
    """PRD F4.2: a scorer infrastructure error fails the item when required.

    Pinned because the code comment used to claim the opposite ("unscored"),
    and a reader who believed it would have mis-read every affected run.
    """
    executor = fake_judge('{"score": 1, "pass": true, "rationale": "seems fine to me"}')
    outcome = await run_judge(CLASS_PARAMS, CASE, "Bob", executor, RUBRIC)

    assert outcome.result.passed is None
    assert outcome.result.error is True
    assert outcome.result.meta["classification"] == UNCLASSIFIED

    agg = aggregate(
        [
            ScoredScorer(
                index=0,
                spec=ScorerSpec(type=ScorerType.llm_judge, params={}, required=True),
                result=outcome.result,
            )
        ]
    )
    assert agg.verdict is False
    assert agg.failing == [0]


async def test_the_contradiction_note_names_the_signal_that_actually_disagreed():
    """The threshold's verdict was being reported as the judge's own flag."""
    executor = fake_judge(
        '{"classification": "INCORRECT", "score": 1, "pass": false, '
        '"rationale": "INCORRECT - names the wrong person."}'
    )
    outcome = await run_judge(
        {**CLASS_PARAMS, "pass_threshold": 0.5}, CASE, "Bob", executor, RUBRIC
    )

    assert outcome.result.passed is False, "the class is the verdict"
    meta = outcome.result.meta
    assert meta["judge_pass"] is False
    assert meta["threshold_pass"] is True
    assert meta["classification_pass"] is False
    assert meta["contradiction"]["overridden"] == "threshold"
    # The old text said "the judge's own pass flag said true". The judge said false.
    assert "pass_threshold said true" in outcome.result.rationale
    assert "judge's own pass flag" not in outcome.result.rationale


async def test_a_passing_class_is_not_described_as_a_failing_one():
    """The note asserted "which the rubric does not pass" unconditionally."""
    executor = fake_judge(
        '{"classification": "CORRECT", "score": 0, "pass": false, '
        '"rationale": "CORRECT: matches the gold answer."}'
    )
    outcome = await run_judge(CLASS_PARAMS, CASE, "Alice", executor, RUBRIC)

    assert outcome.result.passed is True
    assert "which the rubric passes" in outcome.result.rationale
    assert "does not pass" not in outcome.result.rationale


# -- scales --------------------------------------------------------------------


async def test_an_arbitrary_range_scale_normalises_across_its_own_bounds():
    """`1-7` used to reach the percentage clamp, scoring a top mark as 7/100."""
    executor = fake_judge('{"score": 7, "pass": true, "rationale": "top mark"}')
    outcome = await run_judge({"scale": "1-7"}, CASE, "out", executor, RUBRIC)
    assert outcome.result.value == 100.0


async def test_a_scale_with_no_numeric_range_is_refused_before_the_call():
    executor = fake_judge('{"score": 5, "pass": true, "rationale": "x"}')
    outcome = await run_judge({"scale": "likert"}, CASE, "out", executor, RUBRIC)

    assert outcome.result.error is True
    assert "not a scale Gaugix can normalise" in outcome.result.rationale
    assert outcome.usage.prompt_tokens == 0, "an unusable scale must not spend a judge call"


@pytest.mark.parametrize("threshold", ["banana", float("nan"), float("inf"), 8])
async def test_an_invalid_threshold_is_refused_before_the_call(threshold):
    executor = fake_judge('{"score": 5, "pass": true, "rationale": "x"}')
    outcome = await run_judge(
        {"scale": "1-5", "pass_threshold": threshold}, CASE, "out", executor, RUBRIC
    )
    assert outcome.result.error is True
    assert "pass_threshold" in outcome.result.rationale
    assert outcome.usage.prompt_tokens == 0


@pytest.mark.parametrize(
    "params",
    [
        {"classes": 123},
        {"classes": ["CORRECT", ""]},
        {"classes": ["CORRECT", "correct"]},
        {"passing_classes": ["CORRECT"]},
        {"classes": ["CORRECT"], "passing_classes": ["INCORRECT"]},
    ],
)
async def test_an_invalid_class_config_is_a_scorer_error_not_a_crash(params):
    executor = fake_judge('{"classification": "CORRECT", "score": 1, "pass": true}')
    outcome = await run_judge({"scale": "0-1", **params}, CASE, "out", executor, RUBRIC)
    assert outcome.result.error is True
    assert outcome.usage.prompt_tokens == 0


# -- python scorer sandbox -----------------------------------------------------


def test_python_scorer_runs_user_code():
    code = (
        "def score(case, output):\n"
        "    ok = output.strip().endswith('}')\n"
        "    return {'passed': ok, 'value': 100 if ok else 0, 'rationale': 'brace check'}\n"
    )
    result = score_python({"code": code}, CASE, '{"a": 1}')
    assert result.passed is True
    assert result.value == 100.0
    assert result.rationale == "brace check"


def test_python_scorer_sees_the_case():
    code = (
        "def score(case, output):\n"
        "    return {'passed': case['title'] == 'Guardrail decision', 'rationale': case['title']}\n"
    )
    result = score_python({"code": code}, CASE, "out")
    assert result.passed is True
    assert result.rationale == "Guardrail decision"


def test_python_scorer_infers_a_verdict_from_a_bare_value():
    code = "def score(case, output):\n    return {'value': 80}\n"
    assert score_python({"code": code}, CASE, "out").passed is True

    code = "def score(case, output):\n    return {'value': 20}\n"
    assert score_python({"code": code}, CASE, "out").passed is False


@pytest.mark.parametrize("expression", ["float('nan')", "float('inf')", "float('-inf')"])
def test_python_scorer_rejects_non_finite_values(expression):
    code = f"def score(case, output):\n    return {{'value': {expression}}}\n"
    result = score_python({"code": code}, CASE, "out")
    assert result.error is True
    assert "finite number" in result.rationale


def test_python_scorer_timeout_is_contained():
    code = "def score(case, output):\n    while True:\n        pass\n"
    result = score_python({"code": code}, CASE, "out", timeout_s=1.0)
    assert result.passed is None
    assert result.error is True
    assert "timed out" in result.rationale


def test_python_scorer_syntax_error_is_a_scorer_error():
    result = score_python({"code": "def score(:\n"}, CASE, "out")
    assert result.error is True


def test_python_scorer_runtime_error_is_a_scorer_error():
    code = "def score(case, output):\n    return 1 / 0\n"
    result = score_python({"code": code}, CASE, "out")
    assert result.error is True
    assert "ZeroDivisionError" in result.rationale


def test_python_scorer_must_define_score():
    result = score_python({"code": "x = 1\n"}, CASE, "out")
    assert result.error is True
    assert "score(case, output)" in result.rationale


def test_python_scorer_must_return_a_dict():
    result = score_python({"code": "def score(case, output):\n    return True\n"}, CASE, "out")
    assert result.error is True
    assert "expected a dict" in result.rationale


def test_python_scorer_rejects_a_result_with_nothing_in_it():
    result = score_python({"code": "def score(case, output):\n    return {}\n"}, CASE, "out")
    assert result.error is True
    assert "`passed` and/or `value`" in result.rationale


def test_python_scorer_requires_code():
    assert score_python({}, CASE, "out").error is True


def test_python_scorer_cannot_see_provider_credentials(monkeypatch):
    """The sandbox gets a minimal environment — a snippet must not read API keys."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-should-not-be-visible")
    code = (
        "import os\n"
        "def score(case, output):\n"
        "    leaked = os.environ.get('ANTHROPIC_API_KEY')\n"
        "    return {'passed': leaked is None, 'rationale': str(leaked)}\n"
    )
    result = score_python({"code": code}, CASE, "out")
    assert result.passed is True, f"key leaked into the sandbox: {result.rationale}"
