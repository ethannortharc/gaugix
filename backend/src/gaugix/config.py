"""Application configuration (pydantic-settings).

Everything the app needs to boot lives here. Provider API keys are deliberately
*not* modelled as settings fields: per ARCHITECTURE §11 they are read from the
process environment and are only ever surfaced as present/absent plus a masked
suffix (see :func:`provider_key_status`). Production deployments may opt into an
immutable startup snapshot with ``GAUGIX_FREEZE_CREDENTIALS=1``.
"""

from __future__ import annotations

import json
import os
import re
import threading
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

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

# Opt-in production hardening. The snapshot is lazy because create_app()/CLI
# load the repo dotenv after importing this module; taking it at import time
# would silently omit dotenv-only credentials. A lock keeps simultaneous first
# requests on one consistent snapshot.
_FROZEN_CREDENTIAL_ENV: Mapping[str, str] | None = None
_CREDENTIAL_ENV_LOCK = threading.Lock()


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
    instance_id: str | None = Field(default=None, validation_alias="GAUGIX_INSTANCE_ID")
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
    global _FROZEN_CREDENTIAL_ENV
    get_settings.cache_clear()
    with _CREDENTIAL_ENV_LOCK:
        _FROZEN_CREDENTIAL_ENV = None


def mask_key(value: str) -> str:
    """Render a credential as a non-reversible hint (never the key itself)."""
    tail = value[-4:] if len(value) >= 8 else ""
    return f"…{tail}" if tail else "…"


_REDACTED = "[REDACTED]"
_SECRET_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "credentials",
    "password",
    "private_key",
    "proxy_authorization",
    "secret",
    "token",
    "access_token",
    "refresh_token",
    "signing_key",
    "x_api_key",
    "x_mt_vk",
}
_SECRET_VALUE = re.compile(
    r"(?i)\b(?:"
    r"(?:sk|glpat|xox[baprs])-[A-Za-z0-9._-]{8,}|"
    r"(?:gh[pousr]|github_pat)_[A-Za-z0-9._-]{8,}"
    r")"
)
_KEYED_FIELD_PREFIX = re.compile(
    r"""(?<![A-Za-z0-9_-])["']?(?P<field>[A-Za-z][A-Za-z0-9_-]*)"""
    r"""["']?[ \t]*[:=][ \t]*"""
)
_HEADER_CONTAINER_KEYS = {"default_headers", "extra_headers", "headers", "request_headers"}
_PLURAL_SECRET_KEYS = {
    "access_tokens",
    "api_keys",
    "passwords",
    "private_keys",
    "refresh_tokens",
    "secrets",
    "signing_keys",
}
_SAFE_HEADER_NAME = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+")
_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_MAX_REDACTION_DEPTH = 64


def redact_for_display(value: Any, *, _parent_key: str = "", _depth: int = 0) -> Any:
    """Return a JSON-like copy that is safe for APIs and exported reports.

    Frozen profiles should normally contain credential *environment names*, not
    values.  Imported profiles can still carry literal headers or provider
    parameters, so every human-facing snapshot gets a final recursive guard.
    Environment-variable names remain visible because they are reproducibility
    metadata, not credentials.
    """
    if _depth >= _MAX_REDACTION_DEPTH:
        return _REDACTED
    parent = _normalize_key(_parent_key)
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        next_suffix: dict[str, int] = {}
        for raw_key, item in value.items():
            key = str(raw_key)
            normalized = _normalize_key(key)
            safe_key = _SECRET_VALUE.sub(_REDACTED, _redact_secret_fields(key))
            header_value = parent in _HEADER_CONTAINER_KEYS
            header_name = header_value or parent == "request_headers_from_env"
            if header_name and _SAFE_HEADER_NAME.fullmatch(key) is None:
                safe_key = _REDACTED
            base = safe_key
            suffix = next_suffix.get(base, 1)
            safe_key = base if suffix == 1 else f"{base}#{suffix}"
            while safe_key in result:
                suffix += 1
                safe_key = f"{base}#{suffix}"
            next_suffix[base] = suffix + 1
            is_env_name = normalized != "request_headers_from_env" and (
                normalized.endswith("_env") or normalized.endswith("_env_name")
            )
            valid_env_name = (
                is_env_name and isinstance(item, str) and _ENV_NAME.fullmatch(item) is not None
            )
            env_reference = parent == "request_headers_from_env"
            valid_env_reference = (
                env_reference and isinstance(item, str) and _ENV_NAME.fullmatch(item) is not None
            )
            if env_reference and not valid_env_reference:
                result[safe_key] = _REDACTED
                continue
            if is_env_name and not valid_env_name:
                result[safe_key] = _REDACTED
                continue
            plural_secret = normalized in _PLURAL_SECRET_KEYS or (
                normalized == "tokens" and not isinstance(item, (int, float))
            )
            if not env_reference and (
                (_is_secret_field(normalized) and not is_env_name) or plural_secret or header_value
            ):
                result[safe_key] = _REDACTED
            else:
                result[safe_key] = redact_for_display(item, _parent_key=key, _depth=_depth + 1)
        return result
    if isinstance(value, list):
        return [
            redact_for_display(item, _parent_key=_parent_key, _depth=_depth + 1) for item in value
        ]
    if isinstance(value, tuple):
        return [
            redact_for_display(item, _parent_key=_parent_key, _depth=_depth + 1) for item in value
        ]
    if isinstance(value, (bytes, bytearray, memoryview)):
        return _REDACTED
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith(("{", "[")):
            try:
                parsed = json.loads(value)
            except (ValueError, TypeError, RecursionError):
                pass
            else:
                if isinstance(parsed, (dict, list)):
                    return json.dumps(
                        redact_for_display(
                            parsed,
                            _parent_key=_parent_key,
                            _depth=_depth + 1,
                        ),
                        ensure_ascii=False,
                        sort_keys=True,
                    )
        if parent in _HEADER_CONTAINER_KEYS:
            return _REDACTED
        return _SECRET_VALUE.sub(_REDACTED, _redact_secret_fields(value))
    return value


def _is_secret_key(normalized: str) -> bool:
    tokens = normalized.split("_")
    if normalized in _PLURAL_SECRET_KEYS:
        return True
    if any(
        token in {"credential", "credentials", "password", "passwords", "secret", "secrets"}
        for token in tokens
    ):
        return True
    return normalized in _SECRET_KEYS or any(
        normalized.endswith(f"_{secret_key}") for secret_key in _SECRET_KEYS
    )


def _normalize_key(key: str) -> str:
    with_boundaries = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", key)
    return re.sub(r"[^a-z0-9]+", "_", with_boundaries.lower()).strip("_")


def _is_secret_field(normalized: str) -> bool:
    return _is_secret_key(normalized) or "authorization" in normalized.split("_")


def _search_secret_field(value: str, start: int) -> re.Match[str] | None:
    """Find the next keyed field whose normalized name is credential-bearing."""
    cursor = start
    while match := _KEYED_FIELD_PREFIX.search(value, cursor):
        if _is_secret_field(_normalize_key(match.group("field"))):
            return match
        cursor = match.end()
    return None


def _match_secret_field(value: str, start: int) -> re.Match[str] | None:
    match = _KEYED_FIELD_PREFIX.match(value, start)
    if match is not None and _is_secret_field(_normalize_key(match.group("field"))):
        return match
    return None


def _redact_secret_fields(value: str) -> str:
    """Mask keyed values in free-form provider text in one linear pass."""
    out: list[str] = []
    cursor = 0
    while match := _search_secret_field(value, cursor):
        start = match.end()
        field = _normalize_key(match.group("field"))
        folded_value = False
        out.append(value[cursor:start])
        if start >= len(value):
            cursor = start
            break

        if value[start] in "\r\n":
            index = start
            if value[index] == "\r":
                index += 1
            if index < len(value) and value[index] == "\n":
                index += 1
            indent_start = index
            while index < len(value) and value[index] in " \t":
                index += 1
            if index > indent_start and _match_secret_field(value, index) is None:
                out.append(value[start:index])
                start = index
                folded_value = True

        if start >= len(value):
            out.append(_REDACTED)
            cursor = start
            break

        quote = value[start] if value[start] in {'"', "'"} else ""
        if quote:
            index = start + 1
            closed = False
            while index < len(value):
                char = value[index]
                if char == "\\":
                    index = min(index + 2, len(value))
                    continue
                if char == quote:
                    index += 1
                    closed = True
                    break
                index += 1
            out.append(f"{quote}{_REDACTED}{quote if closed else ''}")
            continuation_start = index
            while continuation_start < len(value) and value[continuation_start] in " \t":
                continuation_start += 1
            continued = _consume_indented_continuations(value, continuation_start)
            cursor = continued if continued > continuation_start else index
            continue

        if "authorization" in field.split("_"):
            stop = start
            while stop < len(value) and value[stop] not in "\r\n":
                stop += 1
            line_end = stop
            stop = _consume_indented_continuations(value, stop, stop_at_secret_field=False)
            scheme = value[start:line_end].strip().lower()
            if stop == line_end and scheme in {"basic", "bearer", "token"}:
                continuation = line_end
                if continuation < len(value) and value[continuation] == "\r":
                    continuation += 1
                if continuation < len(value) and value[continuation] == "\n":
                    continuation += 1
                if _KEYED_FIELD_PREFIX.match(value, continuation) is None:
                    while continuation < len(value) and value[continuation] not in "\r\n":
                        continuation += 1
                    stop = _consume_indented_continuations(
                        value,
                        continuation,
                        stop_at_secret_field=False,
                    )
            out.append(_REDACTED)
            cursor = stop
            continue

        if _match_secret_field(value, start) is not None:
            out.append(_REDACTED)
            cursor = start
            continue

        index = start
        if folded_value:
            while index < len(value) and value[index] not in "\r\n":
                index += 1
        else:
            while index < len(value) and value[index] not in " \t\r\n,;}":
                index += 1
            scheme = value[start:index].lower()
            if scheme in {"bearer", "basic"}:
                whitespace_start = index
                while index < len(value) and value[index] in " \t\r\n":
                    index += 1
                # A folded log may put the next keyed field on the following line.
                # Preserve that prefix so the outer loop can redact its value too.
                if _match_secret_field(value, index) is not None:
                    index = whitespace_start
                elif index < len(value) and value[index] in {'"', "'"}:
                    token_quote = value[index]
                    index += 1
                    while index < len(value):
                        char = value[index]
                        if char == "\\":
                            index = min(index + 2, len(value))
                            continue
                        index += 1
                        if char == token_quote:
                            break
                else:
                    while index < len(value) and value[index] not in " \t\r\n,;}\"'":
                        index += 1
        index = _consume_indented_continuations(value, index)
        out.append(_REDACTED)
        cursor = index

    out.append(value[cursor:])
    return "".join(out)


def _consume_indented_continuations(
    value: str,
    index: int,
    *,
    stop_at_secret_field: bool = True,
) -> int:
    """Consume HTTP/YAML-style indented continuation lines after a secret value."""
    while index < len(value) and value[index] in "\r\n":
        line_break = index
        if value[index] == "\r":
            index += 1
        if index < len(value) and value[index] == "\n":
            index += 1
        indent_start = index
        while index < len(value) and value[index] in " \t":
            index += 1
        if index < len(value) and value[index] in "\r\n":
            continue
        if index >= len(value):
            return index
        if index == indent_start or (
            stop_at_secret_field and _match_secret_field(value, index) is not None
        ):
            return line_break
        while index < len(value) and value[index] not in "\r\n":
            index += 1
    return index


def provider_key_status() -> dict[str, dict[str, object]]:
    """Present/absent status of every known provider key, with a masked suffix.

    Never returns key material. Consumed by `GET /api/v1/settings/providers`.
    """
    environment = credential_environment()
    status: dict[str, dict[str, object]] = {}
    for provider, env_name in PROVIDER_KEY_ENV.items():
        raw = environment.get(env_name, "").strip()
        status[provider] = {
            "env_var": env_name,
            "present": bool(raw),
            "masked": mask_key(raw) if raw else None,
        }
    return status


def read_api_key(env_var: str | None) -> str | None:
    """Read a credential from the active (optionally frozen) environment."""
    if not env_var:
        return None
    value = credential_environment().get(env_var, "").strip()
    return value or None


def credential_environment() -> Mapping[str, str]:
    """Return the immutable startup environment when production freezing is enabled."""
    global _FROZEN_CREDENTIAL_ENV
    if os.environ.get("GAUGIX_FREEZE_CREDENTIALS") != "1":
        return os.environ
    with _CREDENTIAL_ENV_LOCK:
        if _FROZEN_CREDENTIAL_ENV is None:
            _FROZEN_CREDENTIAL_ENV = dict(os.environ)
        return _FROZEN_CREDENTIAL_ENV
