"""Loading the eval guide from markdown on disk (PRD F7.1).

Chapters are files, not database rows: they ship with the app, they are edited
in an editor, and they diff in git. The loader reads them once at import and
keeps them in memory — ten short documents is not a caching problem.

Frontmatter is a deliberately tiny YAML subset (`key: value` and `key: [a, b]`)
parsed by hand rather than pulling in a YAML dependency for four fields.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

CONTENT_DIR = Path(__file__).parent / "content"

FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)
#: `## Heading` — the anchors the sidebar and permalinks point at.
HEADING = re.compile(r"^##\s+(.+)$", re.MULTILINE)


@dataclass(slots=True)
class Chapter:
    slug: str
    order: int
    title: str
    summary: str
    tags: list[str] = field(default_factory=list)
    body: str = ""

    @property
    def headings(self) -> list[dict[str, str]]:
        return [
            {"text": text.strip(), "anchor": slugify(text)} for text in HEADING.findall(self.body)
        ]

    @property
    def word_count(self) -> int:
        return len(self.body.split())


def slugify(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9\s-]", "", text.strip().lower())
    return re.sub(r"[\s-]+", "-", cleaned).strip("-")


def _parse_frontmatter(raw: str) -> tuple[dict[str, str | list[str]], str]:
    match = FRONTMATTER.match(raw)
    if not match:
        return {}, raw

    meta: dict[str, str | list[str]] = {}
    for line in match.group(1).splitlines():
        if not line.strip() or ":" not in line:
            continue
        key, _, value = line.partition(":")
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            meta[key.strip()] = [
                item.strip().strip("\"'") for item in value[1:-1].split(",") if item.strip()
            ]
        else:
            meta[key.strip()] = value.strip("\"'")
    return meta, match.group(2)


@lru_cache(maxsize=1)
def chapters() -> list[Chapter]:
    """Every chapter, in reading order. Cached — the files cannot change at runtime."""
    out: list[Chapter] = []
    for path in sorted(CONTENT_DIR.glob("*.md")):
        meta, body = _parse_frontmatter(path.read_text(encoding="utf-8"))
        order_raw = meta.get("order", path.stem.split("-", 1)[0])
        try:
            order = int(str(order_raw))
        except ValueError:
            order = 999
        out.append(
            Chapter(
                slug=str(meta.get("slug") or path.stem.split("-", 1)[-1]),
                order=order,
                title=str(meta.get("title") or path.stem),
                summary=str(meta.get("summary") or ""),
                tags=_tags(meta.get("tags")),
                body=body.strip(),
            )
        )
    out.sort(key=lambda chapter: chapter.order)
    return out


def _tags(raw: str | list[str] | None) -> list[str]:
    if isinstance(raw, list):
        return [str(tag) for tag in raw if tag]
    return [raw] if raw else []


def by_slug(slug: str) -> Chapter | None:
    return next((chapter for chapter in chapters() if chapter.slug == slug), None)


@dataclass(slots=True)
class SearchHit:
    slug: str
    title: str
    #: The matching line, so a result is readable without opening the chapter.
    excerpt: str
    score: int


def search(query: str, *, limit: int = 20) -> list[SearchHit]:
    """Plain substring search over titles, summaries and body lines.

    No index and no stemming: ten chapters is small enough that the honest,
    obvious implementation is also the fast one, and a fuzzy match here would
    mostly produce confident-looking noise.
    """
    needle = query.strip().lower()
    if not needle:
        return []

    hits: list[SearchHit] = []
    for chapter in chapters():
        score = 0
        excerpt = chapter.summary
        if needle in chapter.title.lower():
            score += 10
        if needle in chapter.summary.lower():
            score += 5
        if any(needle in tag.lower() for tag in chapter.tags):
            score += 3

        for line in chapter.body.splitlines():
            if needle in line.lower():
                score += 1
                if score <= 1 or not excerpt:
                    excerpt = line.strip().lstrip("#").strip()

        if score:
            hits.append(
                SearchHit(
                    slug=chapter.slug,
                    title=chapter.title,
                    excerpt=(excerpt[:220] + "…") if len(excerpt) > 220 else excerpt,
                    score=score,
                )
            )

    hits.sort(key=lambda hit: (-hit.score, hit.title))
    return hits[:limit]
