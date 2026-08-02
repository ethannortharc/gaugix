"""DTOs for the learning center (PRD F7)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ChapterSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str
    order: int
    title: str
    summary: str
    tags: list[str]
    word_count: int


class ChapterRead(ChapterSummary):
    """One chapter plus the navigation around it."""

    body: str
    headings: list[dict[str, str]]
    previous: ChapterSummary | None
    next: ChapterSummary | None


class SearchHitRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str
    title: str
    excerpt: str
    score: int
