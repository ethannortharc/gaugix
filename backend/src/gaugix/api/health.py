"""Liveness/readiness endpoint — also the frontend's "backend is up" chip."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from sqlalchemy import text

from gaugix import __version__
from gaugix.config import get_settings
from gaugix.db import get_engine

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, Any]:
    """Report app version, database reachability and the active data directory."""
    settings = get_settings()
    db_state = "ok"
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - only on a broken data dir
        db_state = f"error: {type(exc).__name__}"

    return {
        "status": "ok" if db_state == "ok" else "degraded",
        "version": __version__,
        "db": db_state,
        "data_dir": str(settings.resolved_data_dir),
    }
