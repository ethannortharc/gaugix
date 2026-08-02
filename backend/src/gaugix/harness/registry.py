"""Harness registry: `get(kind) -> Harness`.

`direct` is imported lazily because litellm is a heavyweight import (~1s); tests
that only exercise the fake path should not pay for it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from gaugix.domain import HarnessKind
from gaugix.harness.fake import FakeHarness

if TYPE_CHECKING:  # pragma: no cover
    from gaugix.harness.base import Harness

_SINGLETONS: dict[str, Harness] = {}


def get(kind: str | HarnessKind) -> Harness:
    """Return the harness adapter for `kind`, constructing it once per process."""
    key = str(kind)
    cached = _SINGLETONS.get(key)
    if cached is not None:
        return cached

    harness: Harness
    if key == HarnessKind.fake:
        harness = FakeHarness()
    elif key == HarnessKind.direct:
        from gaugix.harness.direct import DirectHarness

        harness = DirectHarness()
    elif key == HarnessKind.cli:
        from gaugix.harness.cli import CliHarness

        harness = CliHarness()
    else:
        raise ValueError(f"unknown harness kind: {kind!r}")

    _SINGLETONS[key] = harness
    return harness


def available_kinds() -> list[str]:
    """Harness kinds this build can run."""
    return [str(k) for k in (HarnessKind.direct, HarnessKind.fake, HarnessKind.cli)]


def reset() -> None:
    """Drop cached adapters (tests)."""
    _SINGLETONS.clear()
