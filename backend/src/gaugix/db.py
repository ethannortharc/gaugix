"""Database engine and session helpers.

SQLite in WAL mode with foreign keys ON and a generous busy timeout — the
combination ARCHITECTURE §3/§15 prescribes for "engine writes while the API
reads" without hitting `database is locked`.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Engine, event
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from gaugix.config import Settings, get_settings

_engine: Engine | None = None


def _apply_sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA synchronous=NORMAL")
    finally:
        cursor.close()


def make_engine(url: str, *, echo: bool = False, in_memory: bool = False) -> Engine:
    """Create an engine with Gaugix's SQLite pragmas attached."""
    connect_args: dict[str, Any] = {"check_same_thread": False}
    kwargs: dict[str, Any] = {}
    if in_memory:
        # A single shared connection so `:memory:` survives across sessions.
        kwargs["poolclass"] = StaticPool
    engine = create_engine(url, echo=echo, connect_args=connect_args, **kwargs)
    event.listen(engine, "connect", _apply_sqlite_pragmas)
    return engine


def get_engine(settings: Settings | None = None) -> Engine:
    """Process-wide engine singleton."""
    global _engine
    if _engine is None:
        cfg = settings or get_settings()
        cfg.ensure_dirs()
        _engine = make_engine(cfg.database_url)
    return _engine


def set_engine(engine: Engine | None) -> None:
    """Override (or clear) the process engine — used by tests and the CLI."""
    global _engine
    _engine = engine


def create_all(engine: Engine | None = None) -> None:
    """Create every table from the SQLModel metadata.

    Alembic owns schema evolution from M1 onward; this stays for tests and for
    first-boot convenience on a fresh data directory.
    """
    import gaugix.models  # noqa: F401  (registers table metadata)

    SQLModel.metadata.create_all(engine or get_engine())


@contextmanager
def session_scope(engine: Engine | None = None) -> Iterator[Session]:
    """Transactional session: commits on success, rolls back on exception."""
    with Session(engine or get_engine()) as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a session (no implicit commit)."""
    with Session(get_engine()) as session:
        yield session
