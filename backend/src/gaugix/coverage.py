"""What a run actually covered, per set — frozen at plan time.

A run over two of a set's five cases produces a pass rate. That number is a
fact about two cases and looks exactly like a fact about the set, and every
place that aggregates runs — the dashboard trend, the baseline, a diff, an
exported report — will treat it as the latter unless something says otherwise.
So the planner writes down, for each set in the run:

* **selected** — cases actually planned into the run;
* **available** — cases the set held *at that moment*, which is the only
  honest denominator: the set may have grown since, and recomputing today
  would silently restate what the run measured;
* **universe** — a short hash of the exact case ids. Two full runs of the same
  set are only comparable if the set did not change between them, and
  "both were full runs" does not establish that (D-053).

Runs planned before this existed carry no coverage block. They are read as
full, which is what they were: `case_ids` is the feature that made partial runs
possible, and it arrived in the same round as this.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

FULL = "full"
PARTIAL = "partial"


def universe_hash(case_ids: list[int]) -> str:
    """A short, order-independent fingerprint of a set of cases."""
    joined = ",".join(str(i) for i in sorted(case_ids))
    return hashlib.sha256(joined.encode()).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class SetCoverage:
    """One set's share of one run."""

    set_id: int
    set_name: str
    selected: int
    available: int
    universe: str
    #: False for a run planned before coverage was recorded. The two facts are
    #: independent and were briefly conflated into one flag, which is how a
    #: legacy *full* run came to describe itself as "all 0 cases" (D-061).
    sizes_known: bool = True
    #: Whether the run was restricted to chosen cases. For a legacy run this is
    #: inferred from `case_ids` in its config rather than from the sizes.
    restricted: bool = False

    @property
    def is_partial(self) -> bool:
        return self.restricted or (self.sizes_known and self.selected < self.available)

    @property
    def label(self) -> str:
        return PARTIAL if self.is_partial else FULL

    def describe(self) -> str:
        """`2 of 5 cases` — the phrase every surface uses, so they agree.

        Three states, not two: sizes recorded; a legacy full run whose size was
        never written down; and a legacy restricted run whose share was never
        written down. Inventing a number for either of the last two would be
        worse than naming the gap.
        """
        if not self.sizes_known:
            return (
                "part of the set — exact coverage was not recorded"
                if self.restricted
                else "full set — exact size was not recorded"
            )
        plural = "case" if self.available == 1 else "cases"
        if not self.is_partial:
            return f"all {self.available} {plural}"
        return f"{self.selected} of {self.available} {plural}"


def freeze(set_id: int, set_name: str, selected: list[int], available: int) -> dict[str, Any]:
    """The coverage block the planner stores in a run's config."""
    return {
        "id": set_id,
        "name": set_name,
        "selected": len(selected),
        "available": available,
        "universe": universe_hash(selected),
    }


def of_run(config: dict[str, Any]) -> dict[int, SetCoverage]:
    """Coverage per set id, read back from a frozen run config.

    Tolerant by design: a config written before coverage existed reports full
    coverage rather than raising, and a malformed entry is skipped rather than
    breaking every dashboard that reads it.
    """
    # A run from the window between `case_ids` shipping and coverage being
    # recorded: restricted, demonstrably, but with no denominator written down.
    legacy_partial = bool(config.get("case_ids"))

    out: dict[int, SetCoverage] = {}
    for entry in config.get("sets", []):
        if not isinstance(entry, dict):
            continue
        set_id = entry.get("id")
        if set_id is None:
            continue
        selected = entry.get("selected")
        available = entry.get("available")
        sizes_known = isinstance(selected, int) and isinstance(available, int)
        out[int(set_id)] = SetCoverage(
            set_id=int(set_id),
            set_name=str(entry.get("name") or ""),
            selected=int(selected) if isinstance(selected, int) else 0,
            available=int(available) if isinstance(available, int) else 0,
            universe=str(entry.get("universe") or ""),
            sizes_known=sizes_known,
            # A run with sizes says so itself. Without them, `case_ids` is the
            # only evidence, and its absence means the run was whole.
            restricted=(selected < available) if sizes_known else legacy_partial,  # type: ignore[operator]
        )
    return out


def partial_sets(config: dict[str, Any]) -> list[SetCoverage]:
    """Every set this run covered only part of, worst first."""
    rows = [c for c in of_run(config).values() if c.is_partial]
    return sorted(rows, key=lambda c: (c.selected / c.available if c.available else 1, c.set_name))


def is_partial(config: dict[str, Any]) -> bool:
    return bool(partial_sets(config))
