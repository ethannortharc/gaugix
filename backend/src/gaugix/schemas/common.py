"""Shared request/response shapes."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Page[T](BaseModel):
    """A page of results. `total` also travels in the `X-Total-Count` header."""

    items: list[T]
    total: int
    limit: int
    offset: int


class PaginationParams(BaseModel):
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


class OkResponse(BaseModel):
    ok: bool = True
    message: str | None = None


class CountResponse(BaseModel):
    """Result of a bulk operation: how many rows it actually touched."""

    ok: bool = True
    count: int
    message: str | None = None


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: Any | None = None


class ErrorEnvelope(BaseModel):
    """Documented shape of every failure response (ARCHITECTURE §7)."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {"error": {"code": "not_found", "message": "Case 7 does not exist"}}
        }
    )

    error: ErrorDetail
