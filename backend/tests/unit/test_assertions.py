"""Deterministic scorers and the shared JSON extractor (PRD F4.1)."""

from __future__ import annotations

import pytest

from gaugix.domain import CaseSnapshot, Message, Role, ScorerSpec
from gaugix.scoring.assertions import (
    extract_json,
    run_assertion,
    score_contains,
    score_json_schema,
    score_not_contains,
    score_regex,
)

CASE = CaseSnapshot(title="t", input=[Message(role=Role.user, content="x")])


def spec(scorer_type: str, **params: object) -> ScorerSpec:
    return ScorerSpec.model_validate({"type": scorer_type, "params": params})


# -- contains / not_contains ---------------------------------------------------


@pytest.mark.parametrize(
    ("output", "params", "expected"),
    [
        ('{"action": "block"}', {"text": '"action": "block"'}, True),
        ('{"action": "allow"}', {"text": '"action": "block"'}, False),
        ("BLOCK", {"text": "block"}, True),  # case-insensitive by default
        ("BLOCK", {"text": "block", "case_sensitive": True}, False),
        ("block", {"text": "block", "case_sensitive": True}, True),
        ("", {"text": "anything"}, False),
    ],
)
def test_contains(output, params, expected):
    result = score_contains(params, output)
    assert result.passed is expected
    assert result.value == (100.0 if expected else 0.0)
    assert result.rationale


@pytest.mark.parametrize(
    ("output", "params", "expected"),
    [
        ("Here is help", {"text": "I cannot help"}, True),
        ("I cannot help with that", {"text": "I cannot help"}, False),
        ("I CANNOT HELP", {"text": "I cannot help"}, False),
        ("I CANNOT HELP", {"text": "I cannot help", "case_sensitive": True}, True),
    ],
)
def test_not_contains(output, params, expected):
    result = score_not_contains(params, output)
    assert result.passed is expected


def test_contains_without_text_is_a_scorer_error_not_a_failure():
    """A misconfigured scorer must be distinguishable from a model that failed."""
    result = score_contains({}, "anything")
    assert result.passed is None
    assert result.error is True
    assert "required" in result.rationale


# -- regex ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("output", "params", "expected"),
    [
        ("```go\nfunc main() {}", {"pattern": r"^```go\n"}, True),
        ("```python\n", {"pattern": r"^```go\n"}, False),
        ("no fence", {"pattern": r"^```go\n", "should_match": False}, True),
        ("```go\n", {"pattern": r"^```go\n", "should_match": False}, False),
        ("HELLO", {"pattern": "hello", "ignore_case": True}, True),
        ("HELLO", {"pattern": "hello"}, False),
        ("line1\nline2", {"pattern": "^line2", "multiline": True}, True),
        ("line1\nline2", {"pattern": "^line2"}, False),
    ],
)
def test_regex(output, params, expected):
    assert score_regex(params, output).passed is expected


def test_invalid_regex_is_a_scorer_error():
    result = score_regex({"pattern": "([unclosed"}, "anything")
    assert result.passed is None
    assert result.error is True
    assert "invalid pattern" in result.rationale


def test_regex_rationale_quotes_what_matched():
    result = score_regex({"pattern": r"\d+"}, "the answer is 42")
    assert "42" in result.rationale


# -- JSON extraction -----------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('{"a": 1}', {"a": 1}),
        ('  {"a": 1}  ', {"a": 1}),
        ('Sure! Here you go:\n{"a": 1}', {"a": 1}),
        ('```json\n{"a": 1}\n```', {"a": 1}),
        ('```\n{"a": 1}\n```', {"a": 1}),
        ('Here:\n```json\n{"a": 1}\n```\nHope that helps!', {"a": 1}),
        ('[{"a": 1}]', [{"a": 1}]),
        ('{"nested": {"deep": [1, 2]}}', {"nested": {"deep": [1, 2]}}),
        ("not json at all", None),
        ("", None),
    ],
)
def test_extract_json(text, expected):
    assert extract_json(text) == expected


def test_extract_json_ignores_braces_inside_strings():
    """A brace inside a string must not close the object early."""
    text = 'prose {"note": "a } brace", "ok": true} trailing'
    assert extract_json(text) == {"note": "a } brace", "ok": True}


def test_extract_json_prefers_the_whole_string_when_it_parses():
    assert extract_json('{"outer": {"inner": 1}}') == {"outer": {"inner": 1}}


# -- json_schema ---------------------------------------------------------------

BLOCK_SCHEMA = {
    "type": "object",
    "required": ["action"],
    "properties": {"action": {"const": "block"}},
}


def test_json_schema_passes_on_a_valid_payload():
    result = score_json_schema({"schema": BLOCK_SCHEMA}, '{"action": "block"}')
    assert result.passed is True
    assert result.value == 100.0


def test_json_schema_extracts_from_prose_by_default():
    output = 'I would block this.\n```json\n{"action": "block"}\n```'
    assert score_json_schema({"schema": BLOCK_SCHEMA}, output).passed is True


def test_json_schema_can_require_bare_json():
    output = 'Sure!\n{"action": "block"}'
    result = score_json_schema({"schema": BLOCK_SCHEMA, "extract_json": False}, output)
    assert result.passed is False
    assert "not valid JSON" in result.rationale


def test_json_schema_failure_names_the_offending_field():
    result = score_json_schema({"schema": BLOCK_SCHEMA}, '{"action": "allow"}')
    assert result.passed is False
    assert "action" in result.rationale


def test_json_schema_with_no_json_fails_rather_than_erroring():
    """The model produced nothing parseable — that is a real failure, not a bug."""
    result = score_json_schema({"schema": BLOCK_SCHEMA}, "I refuse to answer.")
    assert result.passed is False
    assert result.error is False
    assert "no JSON" in result.rationale


def test_a_broken_schema_is_a_scorer_error():
    result = score_json_schema({"schema": {"type": "not-a-type"}}, '{"a": 1}')
    assert result.passed is None
    assert result.error is True


def test_json_schema_requires_an_object_schema():
    assert score_json_schema({"schema": "nope"}, "{}").error is True


# -- dispatch ------------------------------------------------------------------


def test_run_assertion_dispatches_by_type():
    assert run_assertion(spec("contains", text="hi"), CASE, "hi there").passed is True
    assert run_assertion(spec("regex", pattern="^hi"), CASE, "hi there").passed is True


def test_run_assertion_rejects_a_non_deterministic_type():
    result = run_assertion(spec("llm_judge"), CASE, "x")
    assert result.error is True
    assert "not a deterministic scorer" in result.rationale


def test_a_scorer_that_raises_is_contained():
    """No scorer bug may take down a run."""
    result = run_assertion(spec("contains", text=object()), CASE, "x")
    assert result.passed is None
    assert result.error is True
