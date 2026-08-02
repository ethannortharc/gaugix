"""Harness adapters — how a model gets invoked (direct API, fake, CLI agent)."""

from gaugix.harness.base import Harness
from gaugix.harness.registry import available_kinds, get

__all__ = ["Harness", "available_kinds", "get"]
