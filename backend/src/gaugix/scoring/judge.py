"""LLM-as-judge scoring (PRD F4.1, ARCHITECTURE §6).

Judge calls go through the **harness layer**, not straight to a provider, so their
tokens and cost are captured the same way an eval call's are — a judge is not free,
and a cost-per-quality comparison that ignored it would be wrong.

Parsing is deliberately forgiving in shape and strict in meaning: the verdict may
arrive bare, fenced, or wrapped in prose (the shared JSON extractor handles all
three), but if it cannot be parsed after one corrective retry the result is a
scorer *error*, never a guess.
"""

from __future__ import annotations

import contextlib
import hashlib
from dataclasses import dataclass
from typing import Any

from gaugix.domain import (
    CaseSnapshot,
    ExecutorSnapshot,
    HarnessError,
    InvokeContext,
    Message,
    Role,
    Usage,
)
from gaugix.harness import get as get_harness
from gaugix.scoring.aggregate import NAMED_SCALES, finite_float, normalize_value, scale_bounds
from gaugix.scoring.assertions import ScoreResult, extract_json

DEFAULT_TEMPLATE = """You are grading one response from another model. Be strict and specific.

## Rubric
{rubric}

## The task the model was given
{input}

## Expected answer / notes
{reference}

## The model's response
{output}

## How to reply
Reply with JSON only — no prose, no markdown fence:
{{"score": <number on the {scale} scale>, "pass": <true|false>, "rationale": "<one or two sentences citing what in the response drove the score>"}}"""

RETRY_NUDGE = (
    "Your previous reply could not be parsed. Reply with JSON only, exactly:\n"
    '{"score": <number>, "pass": <true|false>, "rationale": "<text>"}'
)


def retry_nudge(classes: tuple[str, ...]) -> str:
    """The corrective re-ask, naming the rubric's classes when it has any.

    The plain nudge shows a template with no `classification` field, so a judge
    that had just been re-asked was being shown the exact shape that fails a
    class-graded rubric.
    """
    if not classes:
        return RETRY_NUDGE
    options = " | ".join(classes)
    return (
        "Your previous reply could not be used: it did not name one of this "
        f"rubric's classes ({options}). Reply with JSON only, exactly:\n"
        f'{{"classification": "<{options}>", "score": <number>, '
        '"pass": <true|false>, "rationale": "<text>"}'
    )


#: The bucket a class-graded judge lands in when its reply names no class at
#: all. Counted rather than dropped: "fewer classified items than items" is a
#: fact about the judge, and an invisible one if unclassified replies vanish.
UNCLASSIFIED = "UNCLASSIFIED"

#: Kept as a re-export: the bounds now live beside the normalisation that uses
#: them, because two tables meant `percent` could be clamped by one and not the
#: other.
SCALE_BOUNDS = NAMED_SCALES


@dataclass(slots=True)
class JudgeOutcome:
    result: ScoreResult
    usage: Usage
    raw_output: str


def rubric_hash(rubric: str) -> str:
    """Identifies which rubric text produced a score, so edits are traceable."""
    return hashlib.sha256(rubric.encode("utf-8")).hexdigest()[:16]


def build_messages(
    params: dict[str, Any], case: CaseSnapshot, output: str, rubric: str
) -> list[Message]:
    """Render the judge prompt. `template` may override the built-in."""
    template = params.get("template") or DEFAULT_TEMPLATE
    scale = str(params.get("scale") or "1-5")

    body = template.format(
        rubric=rubric,
        input=case.prompt_text(),
        output=output,
        reference=case.reference or "(none provided)",
        scale=scale,
    )
    return [Message(role=Role.user, content=body)]


def _named(raw: Any) -> tuple[str, ...]:
    """A scorer param that is a list of class names, upper-cased and cleaned."""
    if not isinstance(raw, list):
        return ()
    return tuple(str(name).strip().upper() for name in raw if str(name).strip())


#: What may sit between a leading class token and the justification after it.
#: A class token has to *end* — otherwise "CORRECTNESS was not assessed" reads
#: as CORRECT.
_CLASS_DELIMITERS = frozenset(":;-—–.,!|)]}\"'*")


def classify(payload_class: Any, rationale: str, classes: tuple[str, ...]) -> str | None:
    """Which of a rubric's declared classes this verdict is, if any.

    Some rubrics grade into named buckets rather than onto a scale — SimpleQA's
    CORRECT / INCORRECT / NOT_ATTEMPTED is the case in the catalogue, and the
    distinction between a wrong answer and a declined one is the benchmark's
    entire point. Left in prose it is unfilterable and uncountable, which made
    "read the NOT_ATTEMPTED share" advice nobody could follow (D-057).

    Only the two channels the rubric actually asks for are accepted: a
    `classification` field in the judge's JSON, or the class as the **first
    token** of the rationale. Anything else is no classification.

    It used to fall back to scanning the whole rationale for a class name, and
    that fallback inverted verdicts. Ordering longest-first defends against
    containment (INCORRECT beats CORRECT) but nothing defends against negation:
    "the answer is *not correct*" contains CORRECT, and on SimpleQA the class
    *is* the verdict, so a wrong answer passed. "Correctness was not evaluated"
    failed the same way. A judge that will not name its class must be an error,
    not a guess read out of prose (D-066).
    """
    if not classes:
        return None
    if isinstance(payload_class, str):
        named = _canonical_class(payload_class, classes)
        if named is not None:
            return named
    head = rationale.strip().upper().lstrip("*_#[( \t")
    # Longest first, so CORRECT cannot claim a rationale that opens INCORRECT.
    for name in sorted(classes, key=len, reverse=True):
        for spelling in _spellings(name):
            if not head.startswith(spelling):
                continue
            rest = head[len(spelling) :]
            if not rest or rest[0].isspace() or rest[0] in _CLASS_DELIMITERS:
                return name
    return None


def _spellings(name: str) -> tuple[str, ...]:
    """`NOT_ATTEMPTED` also written as `NOT ATTEMPTED` or `NOT-ATTEMPTED`.

    Accepting the separator variants is not a loosening: the token still has to
    open the rationale and still has to end. It keeps a judge that merely
    prettified the class name out of the UNCLASSIFIED bucket, which matters
    more now that prose is no longer scanned as a fallback.
    """
    return tuple({name, name.replace("_", " "), name.replace("_", "-")})


def _canonical_class(value: str, classes: tuple[str, ...]) -> str | None:
    """Map a declared class or one of its separator spellings to its name."""
    candidate = value.strip().upper()
    for name in classes:
        if candidate in _spellings(name):
            return name
    return None


def class_config(
    params: dict[str, Any],
) -> tuple[tuple[str, ...], tuple[str, ...], str | None]:
    """Validate and canonicalise a class-graded judge configuration.

    Scorer params are intentionally an open JSON object, so type-specific
    validation belongs at the scorer boundary. Keeping this shared by preflight
    and runtime prevents a malformed import from either crashing preflight or
    slipping through a re-score that did not run preflight.
    """
    raw_classes = params.get("classes")
    raw_passing = params.get("passing_classes")

    for key, raw in (("classes", raw_classes), ("passing_classes", raw_passing)):
        if raw is not None and not isinstance(raw, list):
            return (), (), f"`{key}` must be a list of non-empty strings"
        if isinstance(raw, list) and any(not isinstance(v, str) or not v.strip() for v in raw):
            return (), (), f"`{key}` must contain only non-empty strings"

    classes = _named(raw_classes)
    passing = _named(raw_passing)
    if len(set(classes)) != len(classes):
        return (), (), "`classes` contains duplicate names"
    owners: dict[str, str] = {}
    for name in classes:
        for spelling in _spellings(name):
            other = owners.setdefault(spelling, name)
            if other != name:
                return (), (), f"`classes` names {other} and {name} overlap"
    if passing and not classes:
        return (), (), "`passing_classes` is set but `classes` is not"
    canonical_passing: list[str] = []
    stray: list[str] = []
    for name in passing:
        canonical = _canonical_class(name, classes)
        if canonical is None:
            stray.append(name)
        else:
            canonical_passing.append(canonical)
    if stray:
        return (
            (),
            (),
            f"`passing_classes` names {', '.join(sorted(set(stray)))}, "
            "which `classes` does not declare",
        )
    if len(set(canonical_passing)) != len(canonical_passing):
        return (), (), "`passing_classes` contains duplicate names"
    return classes, tuple(canonical_passing), None


def threshold_value(raw: Any, scale: str) -> tuple[float | None, str | None]:
    """A finite pass threshold inside the declared scale, or a config error."""
    if raw is None:
        return None, None
    threshold = finite_float(raw)
    if threshold is None:
        return None, f"`pass_threshold` must be a finite number, got {raw!r}"
    bounds = scale_bounds(scale)
    if bounds is None:
        return None, f"`scale` {scale!r} has no numeric range"
    low, high = bounds
    if not low <= threshold <= high:
        return (
            None,
            f"`pass_threshold` {threshold:g} is outside the {scale} scale ({low:g}–{high:g})",
        )
    return threshold, None


def parse_verdict(text: str, scale: str) -> tuple[float | None, bool | None, str] | None:
    """Parse a judge reply into (raw score, pass flag, rationale), or None."""
    payload = extract_json(text)
    if not isinstance(payload, dict):
        return None

    raw_score = payload.get("score", payload.get("rating", payload.get("value")))
    score: float | None
    if raw_score is None:
        score = None
    else:
        score = finite_float(raw_score)
        if score is None:
            return None

    raw_pass = payload.get("pass", payload.get("passed"))
    if isinstance(raw_pass, bool):
        passed: bool | None = raw_pass
    elif isinstance(raw_pass, str) and raw_pass.strip().lower() in {"true", "false"}:
        passed = raw_pass.strip().lower() == "true"
    else:
        passed = None

    rationale = str(payload.get("rationale") or payload.get("reason") or "").strip()

    if score is None and passed is None:
        return None

    # Clamp into the declared scale so a judge that answers "8" on a 1-5 scale
    # cannot push a normalised score above 100.
    bounds = scale_bounds(scale)
    if score is not None and bounds is not None:
        low, high = bounds
        score = max(low, min(high, score))

    return score, passed, rationale


async def run_judge(
    params: dict[str, Any],
    case: CaseSnapshot,
    output: str,
    executor: ExecutorSnapshot,
    rubric: str,
    run_id: int | None = None,
) -> JudgeOutcome:
    """Ask the judge executor to grade one output. Never raises."""
    scale = str(params.get("scale") or "1-5")
    if scale_bounds(scale) is None:
        # Refuse before spending a judge call. Scoring against a scale we cannot
        # place on a number line would produce a number that looks like every
        # other score and means nothing (D-066). Preflight blocks this earlier;
        # this covers a scorer edited after preflight ran.
        return JudgeOutcome(
            result=ScoreResult.scorer_error(
                f"llm_judge: {scale!r} is not a scale Gaugix can normalise — "
                f"use one of {', '.join(sorted(NAMED_SCALES))}, or write it as "
                f"a range like `1-7`"
            ),
            usage=Usage(),
            raw_output="",
        )
    threshold, threshold_error = threshold_value(params.get("pass_threshold"), scale)
    if threshold_error is not None:
        return JudgeOutcome(
            result=ScoreResult.scorer_error(f"llm_judge: {threshold_error}"),
            usage=Usage(),
            raw_output="",
        )
    classes, passing_classes, class_error = class_config(params)
    if class_error is not None:
        return JudgeOutcome(
            result=ScoreResult.scorer_error(f"llm_judge: {class_error}"),
            usage=Usage(),
            raw_output="",
        )
    messages = build_messages(params, case, output, rubric)

    harness = get_harness(executor.harness.kind)
    usage = Usage()
    raw_output = ""

    # Set when attempt 0 parsed but named no class, so the re-ask can say which
    # of the two failures it is correcting.
    nudge = RETRY_NUDGE

    for attempt in range(2):
        judge_case = CaseSnapshot(
            title=f"judge: {case.title}",
            input=(
                messages if attempt == 0 else [*messages, Message(role=Role.user, content=nudge)]
            ),
        )
        ctx = InvokeContext(
            run_id=run_id,
            attempt_n=attempt + 1,
            try_index=attempt,
            harness_config=executor.harness.config,
            params=executor.effective_params(),
            purpose="judge",
        )
        try:
            invocation = await harness.invoke(judge_case, executor.model, ctx)
        except HarnessError as exc:
            return JudgeOutcome(
                result=ScoreResult.scorer_error(
                    f"llm_judge: the judge call failed ({exc.message})"
                ),
                usage=usage,
                raw_output=raw_output,
            )

        raw_output = invocation.output_text
        usage = _accumulate(usage, invocation.usage)

        parsed = parse_verdict(raw_output, scale)
        if parsed is not None:
            score, judge_pass, rationale = parsed
            payload = extract_json(raw_output)
            named = classify(
                payload.get("classification") if isinstance(payload, dict) else None,
                rationale,
                classes,
            )
            # A class-graded rubric that got no class is as unusable as an
            # unparseable reply — under `passing_classes` the class *is* the
            # verdict — so it earns the same one corrective retry rather than
            # going straight to UNCLASSIFIED.
            if classes and named is None and attempt == 0:
                nudge = retry_nudge(classes)
                continue
            return JudgeOutcome(
                result=_finalise(
                    score,
                    judge_pass,
                    rationale,
                    scale,
                    threshold,
                    named,
                    passing_classes,
                    classes,
                ),
                usage=usage,
                raw_output=raw_output,
            )
        # First failure: nudge once. Second: give up honestly.
        if classes:
            nudge = retry_nudge(classes)

    return JudgeOutcome(
        result=ScoreResult.scorer_error(
            f"llm_judge: could not parse a verdict from the judge, even after a retry "
            f"(last reply: {raw_output[:120]!r})"
        ),
        usage=usage,
        raw_output=raw_output,
    )


def _finalise(
    score: float | None,
    judge_pass: bool | None,
    rationale: str,
    scale: str,
    threshold: Any,
    classification: str | None = None,
    passing_classes: tuple[str, ...] = (),
    classes: tuple[str, ...] = (),
) -> ScoreResult:
    normalized = normalize_value(score, scale)

    checked_threshold, threshold_error = threshold_value(threshold, scale)
    if threshold_error is not None:
        return ScoreResult.scorer_error(f"llm_judge: {threshold_error}")

    # Three separate questions, kept separate. Collapsing them into one
    # `passed` variable and then describing it as "the judge's own pass flag"
    # printed the opposite of what happened whenever a threshold had already
    # overridden the judge (D-066).
    threshold_pass: bool | None = None
    if checked_threshold is not None and score is not None:
        # An explicit threshold overrides the judge's own pass field (PRD F4.1) —
        # the user's bar wins over the model's opinion of the bar.
        with contextlib.suppress(TypeError, ValueError):
            threshold_pass = float(score) >= checked_threshold

    passed = judge_pass if threshold_pass is None else threshold_pass
    if passed is None and normalized is not None:
        passed = normalized >= 50

    meta: dict[str, Any] = {"raw_score": score, "scale": scale, "judge_pass": judge_pass}
    if threshold_pass is not None:
        meta["threshold_pass"] = threshold_pass
    if classes:
        meta["classification"] = classification or UNCLASSIFIED

    # A rubric that names its passing classes has said which answer *is* the
    # verdict. SimpleQA's page promises "Gaugix passes only CORRECT"; without
    # this, a judge replying INCORRECT with `pass: true` passed (D-060).
    if passing_classes and classification is not None:
        by_class = classification in passing_classes
        meta["classification_pass"] = by_class
        if passed is not None and passed != by_class:
            meta["contradiction"] = {
                "classification": classification,
                "classification_pass": by_class,
                "judge_pass": judge_pass,
                "threshold_pass": threshold_pass,
                "overridden": "threshold" if threshold_pass is not None else "judge_pass",
                "resolved_as": by_class,
            }
            rationale = f"[{_contradiction_note(classification, by_class, threshold_pass, judge_pass)}] {rationale}"
        passed = by_class

    if classes and classification is None:
        # The judge answered in a shape the rubric did not define, twice (the
        # re-ask in `run_judge` names the classes explicitly). Deciding either
        # way would be inventing a verdict.
        #
        # This is a scorer *infrastructure* error, and PRD F4.2 is explicit
        # about what that means: `passed=None` plus an error rationale, which
        # **fails the item when the scorer is required**, and is remedied by
        # re-scoring (F4.3) — not by re-running the model. So this is not a
        # silent "unscored": the item is failed, visibly and with the cause
        # attached. The UNCLASSIFIED bucket keeps it countable, so a run whose
        # judge drifted off-format reads as a judge problem rather than as the
        # model under test being wrong that often.
        return ScoreResult(
            passed=None,
            value=None,
            error=True,
            rationale=(
                f"llm_judge: the reply named none of the rubric's classes "
                f"({', '.join(classes)}) — got {rationale[:120]!r}"
            ),
            meta=meta,
        )

    return ScoreResult(
        passed=passed,
        value=normalized,
        rationale=rationale or "(the judge gave no rationale)",
        meta=meta,
    )


def _contradiction_note(
    classification: str,
    by_class: bool,
    threshold_pass: bool | None,
    judge_pass: bool | None,
) -> str:
    """Say which signal disagreed with the class, and name it correctly.

    The old wording asserted "which the rubric does not pass" unconditionally,
    so a CORRECT item whose judge flag said false was annotated as though
    CORRECT were a failing class. It also attributed the threshold's verdict to
    the judge. Both went into the stored rationale, i.e. into the audit trail.
    """
    verb = "passes" if by_class else "does not pass"
    if threshold_pass is not None:
        source = f"the pass_threshold said {str(threshold_pass).lower()}"
    else:
        source = f"the judge's own pass flag said {str(judge_pass).lower()}"
    return f"classified {classification}, which the rubric {verb}, while {source}"


def _accumulate(total: Usage, addition: Usage) -> Usage:
    cost = total.cost_usd
    if addition.cost_usd is not None:
        cost = (cost or 0.0) + addition.cost_usd
    return Usage(
        prompt_tokens=total.prompt_tokens + addition.prompt_tokens,
        completion_tokens=total.completion_tokens + addition.completion_tokens,
        cost_usd=cost,
        latency_ms=total.latency_ms + addition.latency_ms,
    )
