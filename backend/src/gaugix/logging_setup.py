"""structlog configuration: pretty console in dev, JSON to a rotating file always."""

from __future__ import annotations

import logging
import logging.handlers
import sys
from typing import Any

import structlog

from gaugix.config import Settings, get_settings

_configured = False


def configure_logging(settings: Settings | None = None) -> None:
    """Idempotently configure stdlib logging + structlog."""
    global _configured
    if _configured:
        return
    cfg = settings or get_settings()
    cfg.ensure_dirs()

    level = getattr(logging, cfg.log_level.upper(), logging.INFO)

    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    structlog.configure(
        processors=[
            *shared,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processor=(
                structlog.processors.JSONRenderer()
                if cfg.log_json
                else structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())
            ),
            foreign_pre_chain=shared,
        )
    )
    root.addHandler(console)

    file_handler = logging.handlers.RotatingFileHandler(
        cfg.logs_dir / "gaugix.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processor=structlog.processors.JSONRenderer(),
            foreign_pre_chain=shared,
        )
    )
    root.addHandler(file_handler)

    # uvicorn's own handlers would double-print; route them through ours.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True

    _configured = True


def get_logger(name: str = "gaugix") -> structlog.stdlib.BoundLogger:
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger
