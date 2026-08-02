"""The eval guide: content is loaded, complete, and searchable (PRD F7.1)."""

from __future__ import annotations

from gaugix.learn import loader

EXPECTED_SLUGS = [
    "why-evaluate",
    "anatomy-of-an-eval",
    "choosing-scorers",
    "writing-good-cases",
    "writing-rubrics",
    "judge-calibration",
    "guardrail-evals",
    "comparing-models-fairly",
    "statistics-you-need",
    "sharing-results-honestly",
]


def test_all_ten_chapters_load_in_order():
    """PRD Appendix C lists ten. A guide with gaps is not a guide."""
    assert [chapter.slug for chapter in loader.chapters()] == EXPECTED_SLUGS
    assert [chapter.order for chapter in loader.chapters()] == list(range(1, 11))


def test_every_chapter_has_a_title_and_a_summary():
    for chapter in loader.chapters():
        assert chapter.title, chapter.slug
        assert chapter.summary, chapter.slug
        assert chapter.tags, chapter.slug


def test_every_chapter_is_substantive():
    """The plan calls this a real deliverable, not filler."""
    for chapter in loader.chapters():
        assert chapter.word_count > 300, f"{chapter.slug} is only {chapter.word_count} words"


def test_chapters_expose_their_headings_as_anchors():
    chapter = loader.by_slug("choosing-scorers")
    assert chapter is not None
    anchors = [heading["anchor"] for heading in chapter.headings]
    assert anchors
    assert all(anchor == loader.slugify(anchor) for anchor in anchors)


def test_an_unknown_slug_is_none():
    assert loader.by_slug("does-not-exist") is None


def test_internal_links_point_at_real_chapters():
    """A dead link in the guide is worse than no link."""
    import re

    slugs = {chapter.slug for chapter in loader.chapters()}
    for chapter in loader.chapters():
        for target in re.findall(r"\]\(/learn/([a-z0-9-]+)\)", chapter.body):
            assert target in slugs, f"{chapter.slug} links to missing chapter {target!r}"


# -- search --------------------------------------------------------------------


def test_search_finds_a_chapter_by_title():
    hits = loader.search("rubric")
    assert hits
    assert hits[0].slug == "writing-rubrics"


def test_search_finds_body_text():
    hits = loader.search("self-preference")
    assert any(hit.slug == "judge-calibration" for hit in hits)


def test_search_returns_a_readable_excerpt():
    hits = loader.search("verbosity")
    assert hits
    assert hits[0].excerpt
    assert "#" not in hits[0].excerpt


def test_search_is_case_insensitive():
    assert loader.search("JUDGE") == loader.search("judge")


def test_an_empty_query_returns_nothing_rather_than_everything():
    assert loader.search("") == []
    assert loader.search("   ") == []


def test_a_query_that_matches_nothing_returns_nothing():
    assert loader.search("zzzzznotpresent") == []


def test_a_title_match_outranks_a_body_mention():
    hits = loader.search("statistics")
    assert hits[0].slug == "statistics-you-need"
