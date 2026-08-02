"""Shared table mixins and JSON column helpers.

SQLite has no JSON type, so JSON columns are TEXT with (de)serialisation at the
edges (ARCHITECTURE §3). The `*_json` fields hold raw JSON strings; each model
exposes typed accessors so callers never touch `json.loads` directly.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    """Timezone-aware UTC now. Every timestamp in Gaugix is UTC."""
    return datetime.now(UTC)


class TimestampMixin(SQLModel):
    """`created_at` / `updated_at` on every table (ARCHITECTURE §3)."""

    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=utcnow, nullable=False)

    def touch(self) -> None:
        self.updated_at = utcnow()


def dump_json(value: Any) -> str:
    """Serialise a JSON column value, accepting pydantic models transparently."""
    if isinstance(value, BaseModel):
        return value.model_dump_json()
    return json.dumps(value, default=_default, ensure_ascii=False)


def _default(obj: Any) -> Any:
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json")
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"not JSON serialisable: {type(obj).__name__}")


def load_json(raw: str | None, fallback: Any = None) -> Any:
    """Parse a JSON column, returning `fallback` for NULL/empty/corrupt values.

    A corrupt JSON column must never take down a list endpoint — the row is still
    worth showing, so we degrade to the fallback rather than raising.
    """
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return fallback


def load_models[T: BaseModel](raw: str | None, model: type[T]) -> list[T]:
    """Parse a JSON array column into a list of pydantic models, skipping bad rows."""
    items = load_json(raw, [])
    if not isinstance(items, list):
        return []
    out: list[T] = []
    for item in items:
        try:
            out.append(model.model_validate(item))
        except Exception:
            continue
    return out


def load_str_list(raw: str | None) -> list[str]:
    """Parse a JSON array of strings (tags), tolerating junk."""
    value = load_json(raw, [])
    if not isinstance(value, list):
        return []
    return [str(v) for v in value if isinstance(v, str | int | float)]
