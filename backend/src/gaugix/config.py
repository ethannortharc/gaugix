"""Application configuration (pydantic-settings).

Everything the app needs to boot lives here. Provider API keys are deliberately
*not* modelled as settings fields: per ARCHITECTURE §11 they are read from the
process environment at call time and are only ever surfaced as present/absent
plus a masked suffix (see :func:`provider_key_status`).
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import dotenv_values
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# repo root = .../gaugix (this file is backend/src/gaugix/config.py)
REPO_ROOT = Path(__file__).resolve().parents[3]

#: Environment variable names holding provider credentials, by provider slug.
PROVIDER_KEY_ENV: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}


class Settings(BaseSettings):
    """Runtime configuration, sourced from the environment and repo-root `.env`."""

    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    host: str = Field(default="127.0.0.1", validation_alias="GAUGIX_HOST")
    port: int = Field(default=8317, validation_alias="GAUGIX_PORT")
    data_dir: Path = Field(default=Path("./data"), validation_alias="GAUGIX_DATA_DIR")
    db_path: Path | None = Field(default=None, validation_alias="GAUGIX_DB_PATH")
    provider_concurrency: int = Field(default=4, validation_alias="GAUGIX_PROVIDER_CONCURRENCY")
    default_concurrency: int = Field(default=4, validation_alias="GAUGIX_DEFAULT_CONCURRENCY")
    smoke_max_calls: int = Field(default=50, validation_alias="GAUGIX_SMOKE_MAX_CALLS")
    log_level: str = Field(default="INFO", validation_alias="GAUGIX_LOG_LEVEL")
    log_json: bool = Field(default=False, validation_alias="GAUGIX_LOG_JSON")
    python_scorer_timeout_s: float = Field(
        default=5.0, validation_alias="GAUGIX_PYTHON_SCORER_TIMEOUT_S"
    )

    @field_validator("host")
    @classmethod
    def _loopback_only(cls, v: str) -> str:
        """Refuse to bind anything but loopback (PRD NFR-S, ARCHITECTURE §10)."""
        if v not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError(
                f"GAUGIX_HOST must stay on loopback (got {v!r}); "
                "Gaugix never binds public interfaces"
            )
        return v

    @property
    def resolved_data_dir(self) -> Path:
        """`data_dir`, made absolute against the repo root when relative."""
        p = self.data_dir.expanduser()
        return p if p.is_absolute() else (REPO_ROOT / p).resolve()

    @property
    def resolved_db_path(self) -> Path:
        """Absolute path of the SQLite database file."""
        if self.db_path is not None:
            p = self.db_path.expanduser()
            return p if p.is_absolute() else (REPO_ROOT / p).resolve()
        return self.resolved_data_dir / "gaugix.db"

    @property
    def artifacts_dir(self) -> Path:
        return self.resolved_data_dir / "artifacts"

    @property
    def logs_dir(self) -> Path:
        return self.resolved_data_dir / "logs"

    @property
    def exports_dir(self) -> Path:
        return self.resolved_data_dir / "exports"

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.resolved_db_path}"

    def ensure_dirs(self) -> None:
        """Create the data directories this process needs. Idempotent."""
        for d in (self.resolved_data_dir, self.artifacts_dir, self.logs_dir, self.exports_dir):
            d.mkdir(parents=True, exist_ok=True)


def load_dotenv_into_environ(path: Path | None = None) -> None:
    """Copy repo-root `.env` values into ``os.environ`` without overriding real env vars.

    pydantic-settings reads `.env` for :class:`Settings`, but provider keys are read
    straight from ``os.environ`` at call time (ARCHITECTURE §11) — so they need to be
    materialised there too. Existing environment values always win.
    """
    # Tests set GAUGIX_SKIP_DOTENV=1 so a real `.env` can never leak credentials
    # into the suite — everything must run on FakeHarness with zero network.
    if os.environ.get("GAUGIX_SKIP_DOTENV") == "1":
        return
    env_path = path or (REPO_ROOT / ".env")
    if not env_path.is_file():
        return
    for key, value in dotenv_values(env_path).items():
        if value is not None and key not in os.environ:
            os.environ[key] = value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton."""
    return Settings()


def reset_settings_cache() -> None:
    """Drop the cached settings — used by tests that manipulate the environment."""
    get_settings.cache_clear()


def mask_key(value: str) -> str:
    """Render a credential as a non-reversible hint (never the key itself)."""
    tail = value[-4:] if len(value) >= 8 else ""
    return f"…{tail}" if tail else "…"


def provider_key_status() -> dict[str, dict[str, object]]:
    """Present/absent status of every known provider key, with a masked suffix.

    Never returns key material. Consumed by `GET /api/v1/settings/providers`.
    """
    status: dict[str, dict[str, object]] = {}
    for provider, env_name in PROVIDER_KEY_ENV.items():
        raw = os.environ.get(env_name, "").strip()
        status[provider] = {
            "env_var": env_name,
            "present": bool(raw),
            "masked": mask_key(raw) if raw else None,
        }
    return status


def read_api_key(env_var: str | None) -> str | None:
    """Read a credential from the environment by variable name, at call time."""
    if not env_var:
        return None
    value = os.environ.get(env_var, "").strip()
    return value or None
