"""Optional tree organisation inside a generic EvalSet."""

from __future__ import annotations

import json

from tests.api.test_cases import make_case, make_set


async def create_node(client, set_id: int, name: str, **overrides):
    response = await client.post(f"/api/v1/sets/{set_id}/nodes", json={"name": name, **overrides})
    assert response.status_code == 201, response.text
    return response.json()


async def test_nodes_form_a_tree_with_counts_paths_and_source_metadata(client):
    eval_set = await make_set(client, name="Large multilingual benchmark")
    root = await create_node(
        client,
        eval_set["id"],
        "Safety",
        description="Safety behaviours",
        provenance={"url": "https://example.test/dataset", "revision": "v2"},
    )
    child = await create_node(
        client,
        eval_set["id"],
        "Chinese",
        parent_id=root["id"],
        description="Chinese-language slice",
    )
    await make_case(
        client,
        title="Child case",
        set_id=eval_set["id"],
        node_id=child["id"],
    )
    await make_case(
        client,
        title="Root case",
        set_id=eval_set["id"],
        node_id=root["id"],
    )

    nodes = (await client.get(f"/api/v1/sets/{eval_set['id']}/nodes")).json()
    by_name = {node["name"]: node for node in nodes}
    assert by_name["Safety"]["direct_case_count"] == 1
    assert by_name["Safety"]["descendant_case_count"] == 2
    assert by_name["Chinese"]["path"] == ["Safety", "Chinese"]
    assert by_name["Chinese"]["depth"] == 1
    assert by_name["Safety"]["provenance"]["revision"] == "v2"
    assert by_name["Chinese"]["provenance"] == {}
    assert by_name["Chinese"]["effective_provenance"]["revision"] == "v2"


async def test_branch_listing_includes_descendants_or_only_direct_cases(client):
    eval_set = await make_set(client)
    root = await create_node(client, eval_set["id"], "Root")
    child = await create_node(client, eval_set["id"], "Child", parent_id=root["id"])
    await make_case(client, title="Direct", set_id=eval_set["id"], node_id=root["id"])
    await make_case(client, title="Nested", set_id=eval_set["id"], node_id=child["id"])

    subtree = await client.get(
        f"/api/v1/sets/{eval_set['id']}/cases", params={"node_id": root["id"]}
    )
    assert [case["title"] for case in subtree.json()] == ["Direct", "Nested"]
    assert subtree.json()[1]["node_path"] == ["Root", "Child"]

    direct = await client.get(
        f"/api/v1/sets/{eval_set['id']}/cases",
        params={"node_id": root["id"], "include_descendants": False},
    )
    assert [case["title"] for case in direct.json()] == ["Direct"]


async def test_cases_can_be_reassigned_without_changing_the_case(client):
    eval_set = await make_set(client)
    node = await create_node(client, eval_set["id"], "Regression")
    case = await make_case(client, set_id=eval_set["id"])

    response = await client.post(
        f"/api/v1/sets/{eval_set['id']}/nodes/assign",
        json={"case_ids": [case["id"]], "node_id": node["id"]},
    )
    assert response.status_code == 200, response.text
    listed = (await client.get(f"/api/v1/sets/{eval_set['id']}/cases")).json()
    assert listed[0]["node_id"] == node["id"]
    assert (await client.get(f"/api/v1/cases/{case['id']}")).json()["title"] == case["title"]


async def test_cycles_cross_set_parents_and_unsafe_deletes_are_rejected(client):
    first = await make_set(client, name="First")
    second = await make_set(client, name="Second")
    root = await create_node(client, first["id"], "Root")
    child = await create_node(client, first["id"], "Child", parent_id=root["id"])
    foreign = await create_node(client, second["id"], "Foreign")

    cross_set = await client.patch(
        f"/api/v1/sets/{first['id']}/nodes/{child['id']}",
        json={"parent_id": foreign["id"]},
    )
    assert cross_set.status_code == 404
    cycle = await client.patch(
        f"/api/v1/sets/{first['id']}/nodes/{root['id']}",
        json={"parent_id": child["id"]},
    )
    assert cycle.status_code == 422
    assert (
        await client.delete(f"/api/v1/sets/{first['id']}/nodes/{root['id']}")
    ).status_code == 409


async def test_purging_a_set_removes_its_tree_but_not_cases(client):
    eval_set = await make_set(client)
    root = await create_node(client, eval_set["id"], "Root")
    child = await create_node(client, eval_set["id"], "Child", parent_id=root["id"])
    case = await make_case(client, set_id=eval_set["id"], node_id=child["id"])

    response = await client.delete(f"/api/v1/sets/{eval_set['id']}", params={"purge": True})
    assert response.status_code == 200, response.text
    assert (await client.get(f"/api/v1/cases/{case['id']}")).status_code == 200


async def test_native_import_and_export_round_trip_group_paths(client):
    eval_set = await make_set(client, name="Imported hierarchy")
    rows = [
        {
            "title": "Mandarin safety",
            "input": [{"role": "user", "content": "你好"}],
            "group_path": ["Safety", "Chinese"],
        },
        {
            "title": "Japanese safety",
            "input": [{"role": "user", "content": "こんにちは"}],
            "group_path": ["Safety", "Japanese"],
        },
    ]
    content = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    imported = await client.post(
        "/api/v1/cases/import",
        json={"content": content, "format": "jsonl", "set_id": eval_set["id"]},
    )
    assert imported.status_code == 200, imported.text
    assert imported.json()["imported"] == 2
    nodes = (await client.get(f"/api/v1/sets/{eval_set['id']}/nodes")).json()
    assert {tuple(node["path"]) for node in nodes} == {
        ("Safety",),
        ("Safety", "Chinese"),
        ("Safety", "Japanese"),
    }

    exported = await client.get(
        "/api/v1/cases/export",
        params={"set_id": eval_set["id"], "format": "jsonl", "download": False},
    )
    exported_rows = [json.loads(line) for line in exported.text.splitlines()]
    assert [row["group_path"] for row in exported_rows] == [
        ["Safety", "Chinese"],
        ["Safety", "Japanese"],
    ]


async def test_import_can_target_a_branch_and_nest_file_groups_below_it(client):
    eval_set = await make_set(client, name="Targeted import")
    destination = await create_node(client, eval_set["id"], "Regression")
    rows = [
        {
            "title": "Directly targeted",
            "input": [{"role": "user", "content": "one"}],
        },
        {
            "title": "Nested target",
            "input": [{"role": "user", "content": "two"}],
            "group_path": ["Chinese", "Prompt injection"],
        },
    ]
    content = "".join(json.dumps(row) + "\n" for row in rows)

    imported = await client.post(
        "/api/v1/cases/import",
        json={
            "content": content,
            "format": "jsonl",
            "set_id": eval_set["id"],
            "node_id": destination["id"],
        },
    )

    assert imported.status_code == 200, imported.text
    cases = (await client.get(f"/api/v1/sets/{eval_set['id']}/cases")).json()
    assert [case["node_path"] for case in cases] == [
        ["Regression"],
        ["Regression", "Chinese", "Prompt injection"],
    ]


async def test_import_branch_requires_its_set(client):
    response = await client.post(
        "/api/v1/cases/import",
        json={
            "content": json.dumps(
                {"title": "Invalid target", "input": [{"role": "user", "content": "x"}]}
            ),
            "node_id": 1,
        },
    )
    assert response.status_code == 422
    assert "node_id requires set_id" in response.text
