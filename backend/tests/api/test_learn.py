"""Learning-center endpoints (PRD F7.1)."""

from __future__ import annotations


async def test_the_table_of_contents_is_in_reading_order(client):
    body = (await client.get("/api/v1/learn")).json()

    assert len(body) == 10
    assert [chapter["order"] for chapter in body] == list(range(1, 11))
    assert body[0]["title"] == "Why evaluate"


async def test_a_chapter_carries_its_body_and_neighbours(client):
    body = (await client.get("/api/v1/learn/writing-rubrics")).json()

    assert body["slug"] == "writing-rubrics"
    assert "anchor" in body["body"].lower()
    assert body["previous"]["slug"] == "writing-good-cases"
    assert body["next"]["slug"] == "judge-calibration"


async def test_the_first_chapter_has_no_previous_and_the_last_no_next(client):
    first = (await client.get("/api/v1/learn/why-evaluate")).json()
    last = (await client.get("/api/v1/learn/sharing-results-honestly")).json()

    assert first["previous"] is None
    assert first["next"]["slug"] == "anatomy-of-an-eval"
    assert last["next"] is None


async def test_an_unknown_chapter_is_a_404(client):
    response = await client.get("/api/v1/learn/no-such-chapter")
    assert response.status_code == 404


async def test_search_returns_ranked_hits(client):
    body = (await client.get("/api/v1/learn/search", params={"q": "judge"})).json()

    assert body
    assert body[0]["score"] >= body[-1]["score"]
    assert all(hit["excerpt"] for hit in body)


async def test_the_search_route_is_not_read_as_a_chapter_name(client):
    """`/learn/search` must not be matched by `/learn/{slug}` (D-010)."""
    response = await client.get("/api/v1/learn/search", params={"q": "judge"})
    assert response.status_code == 200
    assert isinstance(response.json(), list)


async def test_an_empty_search_is_empty_not_everything(client):
    assert (await client.get("/api/v1/learn/search", params={"q": ""})).json() == []
