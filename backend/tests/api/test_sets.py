"""Set API: CRUD, membership, ordering (PRD F1.1)."""

from __future__ import annotations

from tests.api.test_cases import make_case, make_set


async def test_create_and_list_sets(client):
    await make_set(client, name="Guardrails", description="Jailbreaks and lookalikes")
    await make_set(client, name="Go benchmark")

    response = await client.get("/api/v1/sets")
    assert response.status_code == 200
    names = [s["name"] for s in response.json()]
    assert names == ["Go benchmark", "Guardrails"], "sets list alphabetically"
    assert response.headers["X-Total-Count"] == "2"


async def test_set_names_are_unique(client):
    await make_set(client, name="Guardrails")
    response = await client.post("/api/v1/sets", json={"name": "Guardrails"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


async def test_rename_to_an_existing_name_is_rejected(client):
    await make_set(client, name="A")
    other = await make_set(client, name="B")
    response = await client.patch(f"/api/v1/sets/{other['id']}", json={"name": "A"})
    assert response.status_code == 409


async def test_rename_to_the_same_name_is_a_no_op(client):
    eval_set = await make_set(client, name="Stable")
    response = await client.patch(f"/api/v1/sets/{eval_set['id']}", json={"name": "Stable"})
    assert response.status_code == 200


async def test_default_scoring_is_stored_on_the_set(client):
    scoring = [
        {
            "type": "llm_judge",
            "params": {"rubric": "Is it correct?", "scale": "1-5", "pass_threshold": 4},
            "required": True,
            "weight": 2,
        }
    ]
    eval_set = await make_set(client, name="Judged", default_scoring=scoring)
    assert eval_set["default_scoring"][0]["type"] == "llm_judge"
    assert eval_set["default_scoring"][0]["params"]["pass_threshold"] == 4


async def test_generic_evaluation_profile_is_stored_without_guardrail_special_casing(client):
    profile = {
        "kind": "binary_classification",
        "name": "Spam classifier",
        "truth": {"source": "tag", "key": "label"},
        "prediction": {"source": "output_json", "key": "classification"},
        "positive_values": ["spam"],
        "negative_values": ["ham"],
        "positive_label": "spam",
        "negative_label": "ham",
        "false_positive_label": "Ham false-positive rate",
    }
    eval_set = await make_set(client, name="Spam", evaluation_profile=profile)
    assert eval_set["evaluation_profile"]["kind"] == "binary_classification"
    assert eval_set["evaluation_profile"]["prediction"]["key"] == "classification"


async def test_set_rejects_an_unknown_collection(client):
    response = await client.post("/api/v1/sets", json={"name": "Orphan", "collection_id": 999})
    assert response.status_code == 404


async def test_case_count_reflects_live_cases_only(client):
    eval_set = await make_set(client)
    keep = await make_case(client, title="Keep", set_id=eval_set["id"])
    drop = await make_case(client, title="Drop", set_id=eval_set["id"])
    assert (await client.get(f"/api/v1/sets/{eval_set['id']}")).json()["case_count"] == 2

    await client.delete(f"/api/v1/cases/{drop['id']}")
    assert (await client.get(f"/api/v1/sets/{eval_set['id']}")).json()["case_count"] == 1
    assert keep["id"]


async def test_deleting_a_set_never_deletes_its_cases(client):
    eval_set = await make_set(client)
    case = await make_case(client, set_id=eval_set["id"])

    await client.delete(f"/api/v1/sets/{eval_set['id']}")
    assert (await client.get("/api/v1/sets")).json() == []
    # The case is a shared entity; it outlives the set.
    assert (await client.get(f"/api/v1/cases/{case['id']}")).status_code == 200


async def test_set_restore(client):
    eval_set = await make_set(client)
    await client.delete(f"/api/v1/sets/{eval_set['id']}")
    restored = await client.post(f"/api/v1/sets/{eval_set['id']}/restore")
    assert restored.json()["deleted_at"] is None
    assert len((await client.get("/api/v1/sets")).json()) == 1


async def test_trashed_set_rejects_edits_and_attachments(client):
    eval_set = await make_set(client)
    case = await make_case(client)
    await client.delete(f"/api/v1/sets/{eval_set['id']}")

    patched = await client.patch(f"/api/v1/sets/{eval_set['id']}", json={"name": "x"})
    assert patched.status_code == 404
    attach = await client.post(
        f"/api/v1/sets/{eval_set['id']}/cases", json={"case_ids": [case["id"]]}
    )
    assert attach.status_code == 404


# -- membership ----------------------------------------------------------------


async def test_attach_appends_in_the_given_order(client):
    eval_set = await make_set(client)
    a = await make_case(client, title="A")
    b = await make_case(client, title="B")
    c = await make_case(client, title="C")

    response = await client.post(
        f"/api/v1/sets/{eval_set['id']}/cases", json={"case_ids": [c["id"], a["id"], b["id"]]}
    )
    assert response.json()["count"] == 3

    cases = (await client.get(f"/api/v1/sets/{eval_set['id']}/cases")).json()
    assert [x["title"] for x in cases] == ["C", "A", "B"]
    assert [x["position"] for x in cases] == [0, 1, 2]


async def test_attaching_a_case_twice_is_idempotent(client):
    eval_set = await make_set(client)
    case = await make_case(client)
    await client.post(f"/api/v1/sets/{eval_set['id']}/cases", json={"case_ids": [case["id"]]})
    second = await client.post(
        f"/api/v1/sets/{eval_set['id']}/cases", json={"case_ids": [case["id"]]}
    )
    assert second.json()["count"] == 0
    assert len((await client.get(f"/api/v1/sets/{eval_set['id']}/cases")).json()) == 1


async def test_attaching_an_unknown_case_is_404(client):
    eval_set = await make_set(client)
    response = await client.post(f"/api/v1/sets/{eval_set['id']}/cases", json={"case_ids": [999]})
    assert response.status_code == 404
    assert response.json()["error"]["details"]["missing"] == [999]


async def test_detach_leaves_no_position_gaps(client):
    eval_set = await make_set(client)
    cases = [await make_case(client, title=f"C{i}", set_id=eval_set["id"]) for i in range(4)]

    response = await client.post(
        f"/api/v1/sets/{eval_set['id']}/cases/detach",
        json={"case_ids": [cases[1]["id"], cases[2]["id"]]},
    )
    assert response.json()["count"] == 2

    remaining = (await client.get(f"/api/v1/sets/{eval_set['id']}/cases")).json()
    assert [x["title"] for x in remaining] == ["C0", "C3"]
    assert [x["position"] for x in remaining] == [0, 1], "positions are compacted"


async def test_detach_does_not_delete_the_case(client):
    eval_set = await make_set(client)
    case = await make_case(client, set_id=eval_set["id"])
    await client.post(
        f"/api/v1/sets/{eval_set['id']}/cases/detach", json={"case_ids": [case["id"]]}
    )
    assert (await client.get(f"/api/v1/cases/{case['id']}")).status_code == 200


async def test_reorder_sets_explicit_positions(client):
    eval_set = await make_set(client)
    cases = [await make_case(client, title=f"C{i}", set_id=eval_set["id"]) for i in range(3)]

    response = await client.post(
        f"/api/v1/sets/{eval_set['id']}/cases/reorder",
        json={"case_ids": [cases[2]["id"], cases[0]["id"], cases[1]["id"]]},
    )
    assert response.json()["count"] == 3

    reordered = (await client.get(f"/api/v1/sets/{eval_set['id']}/cases")).json()
    assert [x["title"] for x in reordered] == ["C2", "C0", "C1"]


async def test_partial_reorder_keeps_unlisted_cases_after_in_relative_order(client):
    eval_set = await make_set(client)
    cases = [await make_case(client, title=f"C{i}", set_id=eval_set["id"]) for i in range(4)]

    await client.post(
        f"/api/v1/sets/{eval_set['id']}/cases/reorder", json={"case_ids": [cases[3]["id"]]}
    )
    result = (await client.get(f"/api/v1/sets/{eval_set['id']}/cases")).json()
    assert [x["title"] for x in result] == ["C3", "C0", "C1", "C2"]


async def test_reorder_rejects_a_case_that_is_not_a_member(client):
    eval_set = await make_set(client)
    member = await make_case(client, set_id=eval_set["id"])
    stranger = await make_case(client, title="Stranger")

    response = await client.post(
        f"/api/v1/sets/{eval_set['id']}/cases/reorder",
        json={"case_ids": [member["id"], stranger["id"]]},
    )
    assert response.status_code == 422
    assert response.json()["error"]["details"]["unknown"] == [stranger["id"]]


async def test_a_case_can_live_in_two_sets_at_different_positions(client):
    first = await make_set(client, name="First")
    second = await make_set(client, name="Second")
    shared = await make_case(client, title="Shared")
    filler = await make_case(client, title="Filler")

    await client.post(f"/api/v1/sets/{first['id']}/cases", json={"case_ids": [shared["id"]]})
    await client.post(
        f"/api/v1/sets/{second['id']}/cases", json={"case_ids": [filler["id"], shared["id"]]}
    )

    detail = (await client.get(f"/api/v1/cases/{shared['id']}")).json()
    positions = {s["name"]: s["position"] for s in detail["sets"]}
    assert positions == {"First": 0, "Second": 1}


async def test_set_cases_can_be_searched_and_tag_filtered(client):
    eval_set = await make_set(client)
    await make_case(client, title="Goroutine leak", tags=["go"], set_id=eval_set["id"])
    await make_case(client, title="Prompt injection", tags=["guardrail"], set_id=eval_set["id"])

    by_text = await client.get(f"/api/v1/sets/{eval_set['id']}/cases", params={"q": "goroutine"})
    assert [c["title"] for c in by_text.json()] == ["Goroutine leak"]

    by_tag = await client.get(
        f"/api/v1/sets/{eval_set['id']}/cases", params={"tags": ["guardrail"]}
    )
    assert [c["title"] for c in by_tag.json()] == ["Prompt injection"]


async def test_listing_cases_of_an_unknown_set_is_404(client):
    assert (await client.get("/api/v1/sets/999/cases")).status_code == 404
