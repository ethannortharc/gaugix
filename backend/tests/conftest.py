"""Shared fixtures.

Every test gets an isolated data directory and its own SQLite file, so the suite
never touches the developer's real `data/` and can run fully parallel-safe.
Zero network access is required anywhere.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Point Gaugix at a throwaway data directory for the duration of a test."""
    from gaugix import db as db_module
    from gaugix.config import reset_settings_cache

    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("GAUGIX_DATA_DIR", str(data_dir))
    monkeypatch.setenv("GAUGIX_DB_PATH", str(data_dir / "gaugix.db"))
    monkeypatch.setenv("GAUGIX_LOG_LEVEL", "WARNING")
    # Never let the developer's real .env reach the suite.
    monkeypatch.setenv("GAUGIX_SKIP_DOTENV", "1")
    for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(key, raising=False)

    reset_settings_cache()
    db_module.set_engine(None)
    try:
        yield data_dir
    finally:
        db_module.set_engine(None)
        reset_settings_cache()


@pytest.fixture
def engine(isolated_data_dir: Path):
    """A ready-to-use engine with the full schema created."""
    from gaugix.db import create_all, get_engine

    eng = get_engine()
    create_all(eng)
    return eng


@pytest.fixture
def session(engine) -> Iterator[Any]:
    from sqlmodel import Session

    with Session(engine) as s:
        yield s


@pytest.fixture
def app(engine):
    """FastAPI app wired to the isolated database."""
    os.environ["GAUGIX_SKIP_CREATE_ALL"] = "1"
    from gaugix.main import create_app

    application = create_app()
    try:
        yield application
    finally:
        os.environ.pop("GAUGIX_SKIP_CREATE_ALL", None)


@pytest.fixture
async def client(app):
    """httpx AsyncClient bound to the app via ASGITransport (no sockets)."""
    import httpx

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
