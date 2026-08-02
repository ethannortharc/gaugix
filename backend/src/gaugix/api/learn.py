"""The eval guide: table of contents, chapters, search (PRD F7.1)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from gaugix.errors import NotFoundError
from gaugix.learn import loader
from gaugix.schemas.learn import ChapterRead, ChapterSummary, SearchHitRead

router = APIRouter(prefix="/learn", tags=["learn"])


def _summary(chapter: loader.Chapter) -> ChapterSummary:
    return ChapterSummary(
        slug=chapter.slug,
        order=chapter.order,
        title=chapter.title,
        summary=chapter.summary,
        tags=chapter.tags,
        word_count=chapter.word_count,
    )


@router.get("", response_model=list[ChapterSummary])
def list_chapters() -> list[ChapterSummary]:
    """The table of contents, in reading order."""
    return [_summary(chapter) for chapter in loader.chapters()]


@router.get("/search", response_model=list[SearchHitRead])
def search_chapters(q: Annotated[str, Query()] = "") -> list[SearchHitRead]:
    """Substring search across titles, summaries and body text.

    Declared before `/{slug}` so "search" is not read as a chapter name (D-010).
    """
    return [
        SearchHitRead(slug=hit.slug, title=hit.title, excerpt=hit.excerpt, score=hit.score)
        for hit in loader.search(q)
    ]


@router.get("/{slug}", response_model=ChapterRead)
def get_chapter(slug: str) -> ChapterRead:
    chapter = loader.by_slug(slug)
    if chapter is None:
        raise NotFoundError(f"no chapter named {slug!r}")

    ordered = loader.chapters()
    index = ordered.index(chapter)
    return ChapterRead(
        **_summary(chapter).model_dump(),
        body=chapter.body,
        headings=chapter.headings,
        previous=_summary(ordered[index - 1]) if index > 0 else None,
        next=_summary(ordered[index + 1]) if index + 1 < len(ordered) else None,
    )
