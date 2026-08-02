"""Apply Alembic migrations programmatically.

Gaugix is a local-first single-user app: nobody should have to run
`alembic upgrade head` by hand after a `git pull`. The server does it on boot.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

from gaugix.config import Settings, get_settings
from gaugix.logging_setup import get_logger

log = get_logger("gaugix.migrate")

BACKEND_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = BACKEND_ROOT / "alembic.ini"


def alembic_config(database_url: str | None = None) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    if database_url:
        cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


def upgrade_to_head(settings: Settings | None = None) -> None:
    """Bring the configured database up to the latest revision."""
    cfg = settings or get_settings()
    cfg.ensure_dirs()
    command.upgrade(alembic_config(cfg.database_url), "head")
    log.info("migrations_applied", db=str(cfg.resolved_db_path))
