"""Turning a list of scorer results into one verdict and one number.

The exact rules (PRD F4.2, ARCHITECTURE §5/§6), because every downstream number
depends on them:

* **Verdict** = every `required` scorer passed, computed over **resolved** scorers
  only. A `human` scorer with no human score yet is *unresolved*: it is excluded
  from the verdict and instead flags the item `needs_human`.
* A `required` scorer that hit an infrastructure error (bad regex, crashed python
  scorer, unparseable judge) counts as a failure — its Score is stored with
  `passed=None` plus the error, so the cause is visible and re-scorable.
* **Numeric score** = weighted mean of scorer values, normalised to 0–100.
* A **human** score overrides the auto/judge result for that same scorer index.
* No resolved scorers at all → verdict `None`. The item is "done (unscored)", not
  "passed" — claiming a pass when nothing was checked would be a lie.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from gaugix.domain import ScorerSpec, ScorerType
from gaugix.scoring.assertions import ScoreResult


@dataclass(slots=True)
class ScoredScorer:
    """One scorer's spec paired with its latest result (human wins if present)."""

    index: int
    spec: ScorerSpec
    result: ScoreResult | None
    source: str = "auto"

    @property
    def resolved(self) -> bool:
        return self.result is not None


@dataclass(slots=True)
class Aggregate:
    verdict: bool | None
    score_value: float | None
    needs_human: bool
    resolved_count: int = 0
    failing: list[int] = field(default_factory=list)


#: The scale vocabulary, in one place. Both the clamp applied when a judge
#: overshoots its scale and the 0–100 mapping read off it, so the two cannot
#: disagree about what `1-5` means.
NAMED_SCALES: dict[str, tuple[float, float]] = {
    "0-100": (0.0, 100.0),
    "percent": (0.0, 100.0),
    "binary": (0.0, 1.0),
    "0-1": (0.0, 1.0),
    "1-5": (1.0, 5.0),
    "1-10": (1.0, 10.0),
}

#: Any `low-high` scale written out, e.g. `1-7`. Reading the general form is
#: what stops the next unlisted scale repeating the `0-1` bug rather than
#: merely patching that one instance of it.
_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)"
_RANGE = re.compile(rf"^({_NUMBER})\s*-\s*({_NUMBER})$")

#: What an unset scale means. Judge params default to `1-5`; a stored value
#: that never had a scale is a raw percentage.
DEFAULT_BOUNDS = (0.0, 100.0)


def finite_float(value: object) -> float | None:
    """A real, finite number, rejecting booleans and numeric lookalikes.

    Python accepts ``float("NaN")`` and the standard JSON decoder accepts bare
    ``NaN``/``Infinity``. Feeding either into ``min``/``max`` does not preserve
    an unknown result: it can collapse to the upper bound and turn an invalid
    score into 100. Every scorer boundary uses this helper so non-finite values
    become visible infrastructure errors instead of plausible numbers.
    """
    if isinstance(value, bool):
        return None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def scale_bounds(scale: str | None) -> tuple[float, float] | None:
    """The `(low, high)` a scale runs between, or None if it is not a scale.

    None is the answer for `likert` or `A-F` — things that name no numeric
    range. Callers must treat that as a configuration error rather than
    guessing, which is the whole point (see `normalize_value`).
    """
    if scale is None or not str(scale).strip():
        return DEFAULT_BOUNDS
    key = str(scale).strip().lower()
    if key in NAMED_SCALES:
        return NAMED_SCALES[key]
    match = _RANGE.match(key)
    if match:
        low, high = float(match.group(1)), float(match.group(2))
        if high > low:
            return low, high
    return None


def normalize_value(value: float | None, scale: str | None) -> float | None:
    """Map a scorer's raw value onto 0–100 (PRD F4.2).

    This used to be a ladder of `if scale ==` with a percentage clamp at the
    bottom, and the clamp was the bug: `0-1` was not on the ladder, so SimpleQA
    and TruthfulQA scored a correct answer as **1.0 out of 100** everywhere a
    score is shown (D-060). Listing `0-1` fixed that instance and left the
    mechanism: `scale="1-7"` still scored a perfect 7 as 7 out of 100.

    So the fallback is gone. A scale is now either something we can place on a
    number line — named, or written `low-high` — or it is not a scale, and an
    unmappable one returns None instead of a plausible wrong number. Preflight
    rejects those before a run starts (D-066).
    """
    if value is None:
        return None
    number = finite_float(value)
    if number is None:
        return None
    if scale is not None and str(scale).strip().lower() == "binary":
        # Binary is a *decision*: anything short of 1 is a 0, not a fraction.
        return 100.0 if number >= 1 else 0.0
    bounds = scale_bounds(scale)
    if bounds is None:
        return None
    low, high = bounds
    return _clamp((number - low) / (high - low) * 100.0)


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, float(value)))


def aggregate(scored: list[ScoredScorer]) -> Aggregate:
    """Compute the verdict, the 0–100 score, and whether a human is still needed."""
    needs_human = any(s.spec.type == ScorerType.human and not s.resolved for s in scored)
    resolved = [s for s in scored if s.resolved and s.result is not None]

    if not resolved:
        # Nothing decided anything. Verdict stays unknown on purpose.
        return Aggregate(verdict=None, score_value=None, needs_human=needs_human, resolved_count=0)

    failing: list[int] = []
    for item in resolved:
        if not item.spec.required or item.result is None:
            continue
        # `passed is None` here means the scorer errored out. A required scorer
        # that could not decide cannot be treated as a pass.
        if item.result.passed is not True:
            failing.append(item.index)

    has_required = any(s.spec.required for s in resolved)
    verdict: bool | None = (len(failing) == 0) if has_required else None

    # (value, weight) pairs, so the arithmetic below has no Optionals in it.
    numeric: list[tuple[float, float]] = [
        (s.result.value, max(0.0, s.spec.weight))
        for s in resolved
        if s.result is not None and s.result.value is not None
    ]
    score_value: float | None = None
    if numeric:
        total_weight = sum(weight for _, weight in numeric)
        if total_weight > 0:
            weighted = sum(value * weight for value, weight in numeric)
            score_value = round(weighted / total_weight, 2)
        else:
            # Every weight is zero: fall back to an unweighted mean rather than
            # dividing by zero or silently dropping the scores.
            score_value = round(sum(value for value, _ in numeric) / len(numeric), 2)

    # No required scorers but some optional ones ran: the numeric score is
    # meaningful, the pass/fail question was never asked.
    if verdict is None and not has_required:
        return Aggregate(
            verdict=None,
            score_value=score_value,
            needs_human=needs_human,
            resolved_count=len(resolved),
        )

    return Aggregate(
        verdict=verdict,
        score_value=score_value,
        needs_human=needs_human,
        resolved_count=len(resolved),
        failing=failing,
    )
