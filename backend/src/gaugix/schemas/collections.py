"""DTOs for the generic evaluation collection hierarchy."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Visibility = Literal["primary", "fixture", "hidden"]


def _clean_tags(tags: list[str]) -> list[str]:
    return sorted({tag.strip() for tag in tags if tag and tag.strip()})


class CollectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    name: str = Field(min_length=1)
    description: str | None = None
    parent_id: int | None = None
    position: int | None = Field(default=None, ge=0)
    visibility: Visibility = "primary"
    tags: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)

    @field_validator("tags")
    @classmethod
    def _tags(cls, value: list[str]) -> list[str]:
        return _clean_tags(value)


class CollectionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str | None = Field(
        default=None,
        min_length=1,
        max_length=160,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    name: str | None = Field(default=None, min_length=1)
    description: str | None = None
    parent_id: int | None = None
    position: int | None = Field(default=None, ge=0)
    visibility: Visibility | None = None
    tags: list[str] | None = None
    provenance: dict[str, Any] | None = None

    @field_validator("tags")
    @classmethod
    def _tags(cls, value: list[str] | None) -> list[str] | None:
        return _clean_tags(value) if value is not None else None


class CollectionRead(BaseModel):
    id: int
    key: str
    name: str
    description: str | None
    parent_id: int | None
    position: int
    visibility: Visibility
    tags: list[str]
    provenance: dict[str, Any]
    path: list[str]
    depth: int
    direct_set_count: int
    descendant_set_count: int
    direct_case_count: int
    descendant_case_count: int
    created_at: datetime
    updated_at: datetime
