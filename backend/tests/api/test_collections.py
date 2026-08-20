"""Generic collection hierarchy above eval sets."""

from __future__ import annotations

from tests.api.test_cases import make_case, make_set


async def create_collection(client, **overrides):
    payload = {
        "key": "suite",
        "name": "Quality suite",
        "description": "Open-ended generation quality",
        **overrides,
    }
    response = await client.post("/api/v1/collections", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


async def test_collection_tree_rolls_up_set_and_case_counts(client):
    root = await create_collection(client)
    child = await create_collection(
        client,
        key="suite.translation",
        name="Translation",
        parent_id=root["id"],
    )
    direct = await make_set(client, name="Direct", collection_id=root["id"])
    nested = await make_set(
        client,
        name="Nested",
        collection_id=child["id"],
        logical_key="translation",
        variant="multilingual",
    )
    await make_case(client, title="Root case", set_id=direct["id"])
    await make_case(client, title="Nested one", set_id=nested["id"])
    await make_case(client, title="Nested two", set_id=nested["id"])

    rows = (await client.get("/api/v1/collections")).json()
    by_key = {row["key"]: row for row in rows}
    assert by_key["suite"]["path"] == ["Quality suite"]
    assert by_key["suite"]["direct_set_count"] == 1
    assert by_key["suite"]["descendant_set_count"] == 2
    assert by_key["suite"]["direct_case_count"] == 1
    assert by_key["suite"]["descendant_case_count"] == 3
    assert by_key["suite.translation"]["path"] == ["Quality suite", "Translation"]


async def test_sets_can_be_filtered_by_collection_tree_and_visibility(client):
    root = await create_collection(client)
    child = await create_collection(client, key="suite.child", name="Child", parent_id=root["id"])
    await make_set(client, name="Root set", collection_id=root["id"])
    await make_set(client, name="Child set", collection_id=child["id"])
    await make_set(
        client,
        name="Fixture",
        collection_id=child["id"],
        visibility="fixture",
    )
    await make_set(client, name="Unfiled")

    recursive = await client.get(
        "/api/v1/sets",
        params={"collection_id": root["id"], "visibility": "primary", "limit": 500},
    )
    assert [row["name"] for row in recursive.json()] == ["Child set", "Root set"]

    direct = await client.get(
        "/api/v1/sets",
        params={"collection_id": root["id"], "include_descendants": False},
    )
    assert [row["name"] for row in direct.json()] == ["Root set"]

    fixture = await client.get("/api/v1/sets", params={"visibility": "fixture"})
    assert [row["name"] for row in fixture.json()] == ["Fixture"]
    unfiled = await client.get("/api/v1/sets", params={"unfiled": True})
    assert [row["name"] for row in unfiled.json()] == ["Unfiled"]


async def test_set_read_exposes_catalogue_metadata(client):
    collection = await create_collection(client, key="retrieval", name="Retrieval")
    eval_set = await make_set(
        client,
        name="Recall @ 10",
        collection_id=collection["id"],
        logical_key="retrieval-recall",
        variant="english",
        visibility="primary",
    )
    assert eval_set["collection_key"] == "retrieval"
    assert eval_set["collection_path"] == ["Retrieval"]
    assert eval_set["logical_key"] == "retrieval-recall"
    assert eval_set["variant"] == "english"


async def test_collection_cycles_and_nonempty_deletes_are_rejected(client):
    root = await create_collection(client)
    child = await create_collection(client, key="suite.child", name="Child", parent_id=root["id"])
    cycle = await client.patch(f"/api/v1/collections/{root['id']}", json={"parent_id": child["id"]})
    assert cycle.status_code == 422

    blocked = await client.delete(f"/api/v1/collections/{root['id']}")
    assert blocked.status_code == 409
    assert (await client.delete(f"/api/v1/collections/{child['id']}")).status_code == 200
    assert (await client.delete(f"/api/v1/collections/{root['id']}")).status_code == 200
