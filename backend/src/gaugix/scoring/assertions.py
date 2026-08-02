"""Deterministic scorers: contains, not_contains, regex, json_schema.

Pure functions over (case snapshot, output text) — no database, no network, no
clock. That is what makes them cheap to test exhaustively and safe to re-run
against stored outputs during a re-score (PRD F4.3).

Every scorer returns a :class:`ScoreResult` rather than raising: a broken *config*
(bad regex, malformed schema) is a scorer-infrastructure error that must be visible
and fixable by editing the config, never a reason to re-invoke the model.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from gaugix.domain import CaseSnapshot, ScorerSpec, ScorerType


@dataclass(slots=True)
class ScoreResult:
    """One scorer's outcome.

    `passed=None` means the scorer could not decide — a config or runtime error.
    It is recorded with an explanatory rationale and only fails the item when the
    scorer is `required` (PRD F4.2).
    """

    passed: bool | None
    value: float | None = None
    rationale: str = ""
    error: bool = False
    meta: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def scorer_error(cls, message: str) -> ScoreResult:
        return cls(passed=None, value=None, rationale=message, error=True)


# -- JSON extraction -----------------------------------------------------------

_FENCE = re.compile(r"```(?:json|JSON)?\s*\n(.*?)```", re.DOTALL)


def extract_json(text: str) -> Any | None:
    """Pull a JSON value out of prose.

    Models wrap JSON in fences, prefix it with "Sure!", or emit it bare. Tried in
    order: whole string → fenced block → first balanced `{…}` or `[…]`. Shared by
    `json_schema` and the judge parser so both accept the same shapes.
    """
    if not text:
        return None

    stripped = text.strip()
    parsed = _try_load(stripped)
    if parsed is not None:
        return parsed

    for match in _FENCE.finditer(text):
        parsed = _try_load(match.group(1).strip())
        if parsed is not None:
            return parsed

    for opener, closer in (("{", "}"), ("[", "]")):
        block = _balanced_block(text, opener, closer)
        if block is not None:
            parsed = _try_load(block)
            if parsed is not None:
                return parsed
    return None


def _try_load(candidate: str) -> Any | None:
    if not candidate:
        return None
    try:
        return json.loads(candidate)
    except (json.JSONDecodeError, ValueError):
        return None


def _balanced_block(text: str, opener: str, closer: str) -> str | None:
    """First balanced `opener…closer` span, ignoring brackets inside strings."""
    start = text.find(opener)
    if start == -1:
        return None

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


# -- scorers -------------------------------------------------------------------


def score_contains(params: dict[str, Any], output: str) -> ScoreResult:
    text = params.get("text")
    if not isinstance(text, str) or text == "":
        return ScoreResult.scorer_error("contains: `text` param is required and must be non-empty")

    case_sensitive = bool(params.get("case_sensitive", False))
    haystack = output if case_sensitive else output.lower()
    needle = text if case_sensitive else text.lower()
    hit = needle in haystack

    return ScoreResult(
        passed=hit,
        value=100.0 if hit else 0.0,
        rationale=(f"found {text!r}" if hit else f"{text!r} not present in the output"),
    )


def score_not_contains(params: dict[str, Any], output: str) -> ScoreResult:
    text = params.get("text")
    if not isinstance(text, str) or text == "":
        return ScoreResult.scorer_error(
            "not_contains: `text` param is required and must be non-empty"
        )

    case_sensitive = bool(params.get("case_sensitive", False))
    haystack = output if case_sensitive else output.lower()
    needle = text if case_sensitive else text.lower()
    hit = needle in haystack

    return ScoreResult(
        passed=not hit,
        value=0.0 if hit else 100.0,
        rationale=(
            f"{text!r} appears in the output (it must not)"
            if hit
            else f"{text!r} absent, as required"
        ),
    )


def score_regex(params: dict[str, Any], output: str) -> ScoreResult:
    pattern = params.get("pattern")
    if not isinstance(pattern, str) or pattern == "":
        return ScoreResult.scorer_error("regex: `pattern` param is required")

    should_match = bool(params.get("should_match", True))
    flags = 0
    if params.get("ignore_case"):
        flags |= re.IGNORECASE
    if params.get("multiline"):
        flags |= re.MULTILINE
    if params.get("dotall"):
        flags |= re.DOTALL

    try:
        compiled = re.compile(pattern, flags)
    except re.error as exc:
        # A bad pattern is a config bug — surface it rather than failing the model.
        return ScoreResult.scorer_error(f"regex: invalid pattern ({exc})")

    found = compiled.search(output)
    matched = found is not None
    passed = matched if should_match else not matched

    detail = f"matched {found.group(0)[:60]!r}" if found is not None else "no match"
    verb = "must match" if should_match else "must not match"

    return ScoreResult(
        passed=passed,
        value=100.0 if passed else 0.0,
        rationale=f"{verb} /{pattern}/ — {detail}",
    )


def score_json_schema(params: dict[str, Any], output: str) -> ScoreResult:
    schema = params.get("schema")
    if not isinstance(schema, dict):
        return ScoreResult.scorer_error("json_schema: `schema` param must be an object")

    payload: Any
    if params.get("extract_json", True):
        payload = extract_json(output)
        if payload is None:
            return ScoreResult(
                passed=False,
                value=0.0,
                rationale="no JSON found in the output",
            )
    else:
        payload = _try_load(output.strip())
        if payload is None:
            return ScoreResult(passed=False, value=0.0, rationale="the output is not valid JSON")

    try:
        import jsonschema

        jsonschema.validate(instance=payload, schema=schema)
    except ImportError:  # pragma: no cover - jsonschema is a hard dependency
        return ScoreResult.scorer_error("json_schema: jsonschema is not installed")
    except Exception as exc:
        message = getattr(exc, "message", str(exc))
        if type(exc).__name__ == "SchemaError":
            return ScoreResult.scorer_error(
                f"json_schema: the schema itself is invalid ({message})"
            )
        path = ".".join(str(p) for p in getattr(exc, "absolute_path", []) or [])
        where = f" at `{path}`" if path else ""
        return ScoreResult(passed=False, value=0.0, rationale=f"schema violation{where}: {message}")

    return ScoreResult(passed=True, value=100.0, rationale="output validates against the schema")


#: Scorer types this module can evaluate synchronously with no side effects.
DETERMINISTIC_TYPES = frozenset(
    {
        ScorerType.contains,
        ScorerType.not_contains,
        ScorerType.regex,
        ScorerType.json_schema,
    }
)

_DISPATCH = {
    ScorerType.contains: score_contains,
    ScorerType.not_contains: score_not_contains,
    ScorerType.regex: score_regex,
    ScorerType.json_schema: score_json_schema,
}


def run_assertion(spec: ScorerSpec, case: CaseSnapshot, output: str) -> ScoreResult:
    """Evaluate one deterministic scorer. `case` is unused today but part of the
    signature every scorer shares, so callers need no special-casing."""
    handler = _DISPATCH.get(ScorerType(spec.type))
    if handler is None:
        return ScoreResult.scorer_error(f"{spec.type} is not a deterministic scorer")
    try:
        return handler(spec.params, output)
    except Exception as exc:
        return ScoreResult.scorer_error(f"{spec.type} raised {type(exc).__name__}: {exc}")
