"""Reading per-model rates out of litellm's bundled cost map.

Gaugix prices a call from litellm's own calculation first (`harness/direct.py`).
The settings pricing table is the fallback for everything litellm cannot price —
local models, proxies, a provider whose rates changed since the wheel was cut.

Starting that table empty made it useless: a user had to already know the rates
to fill it in. Instead it is **seeded** from the same map litellm prices with, so
the numbers are visible and editable rather than implicit. A row the user has
touched is `manual` and is never overwritten by a later pull.

The map is the copy bundled with litellm (see `gaugix/__init__.py`) — no network,
which also means it can go stale. That is why every row stays editable.
"""

from __future__ import annotations

from typing import Any

from gaugix.domain import Pricing, Provider

PER_MILLION = 1_000_000


def _candidate_keys(model_id: str, provider: str | None) -> list[str]:
    """The names litellm might file this model under, best guess first."""
    candidates = [model_id]
    if "/" in model_id:
        candidates.append(model_id.split("/", 1)[1])
    if provider:
        prefix = "gemini" if provider == Provider.gemini else provider
        candidates.append(f"{prefix}/{model_id}")
    # de-duplicate, preserve order
    seen: set[str] = set()
    unique: list[str] = []
    for candidate in candidates:
        if candidate not in seen:
            seen.add(candidate)
            unique.append(candidate)
    return unique


def _entry_to_pricing(entry: Any) -> Pricing | None:
    if not isinstance(entry, dict):
        return None
    try:
        input_rate = float(entry.get("input_cost_per_token") or 0.0) * PER_MILLION
        output_rate = float(entry.get("output_cost_per_token") or 0.0) * PER_MILLION
    except (TypeError, ValueError):
        return None
    # Both zero means litellm has the model but no rates for it — that is not a
    # price, and recording it would show a confident $0.00 for a paid call.
    if input_rate <= 0 and output_rate <= 0:
        return None
    return Pricing(input_per_1m=input_rate, output_per_1m=output_rate)


def lookup_pricing(model_id: str, provider: str | None = None) -> Pricing | None:
    """litellm's published rates for one model, or None if it does not know it."""
    if not model_id:
        return None
    try:
        import litellm
    except Exception:  # pragma: no cover - litellm is a hard dependency
        return None

    cost_map = getattr(litellm, "model_cost", None)
    if not isinstance(cost_map, dict):
        return None

    for key in _candidate_keys(model_id, provider):
        pricing = _entry_to_pricing(cost_map.get(key))
        if pricing is not None:
            return pricing
    return None
