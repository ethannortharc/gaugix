"""Harness protocol — the single seam between the engine and "how a model is called".

ARCHITECTURE §4. Adding a new harness kind (`http`, PRD §9) means writing one
module implementing :class:`Harness` and registering it in `gaugix.harness.registry`;
nothing in the engine changes.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from gaugix.domain import (
    ArtifactIn,
    CaseSnapshot,
    HarnessError,
    InvocationResult,
    InvokeContext,
    ModelSnapshot,
    Usage,
)

__all__ = [
    "ArtifactIn",
    "CaseSnapshot",
    "Harness",
    "HarnessError",
    "InvocationResult",
    "InvokeContext",
    "ModelSnapshot",
    "Usage",
    "estimate_tokens",
]


@runtime_checkable
class Harness(Protocol):
    """Invokes a model for one case and reports what happened."""

    kind: str

    async def invoke(
        self, case: CaseSnapshot, model: ModelSnapshot, ctx: InvokeContext
    ) -> InvocationResult:
        """Run one attempt.

        Raise :class:`HarnessError` (with ``retryable=True`` for transient provider
        failures) rather than returning a sentinel — the runner's retry wrapper keys
        off that flag.
        """
        ...


def estimate_tokens(text: str) -> int:
    """Rough token count for harnesses that report none (~4 chars/token)."""
    return max(1, len(text) // 4) if text else 0
