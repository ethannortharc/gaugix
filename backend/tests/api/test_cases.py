"""Case API: CRUD, search, bulk ops, trash, and import atomicity (PRD F1)."""

from __future__ import annotations

import json

import pytest

CASE = {"title": "Say hello", "input": [{"role": "user", "content": "hi"}], "tags": ["smoke"]}


async def make_case(client, **overrides):
    payload = {**CASE, **overrides}
    response = await client.post("/api/v1/cases", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


async def make_set(client, name="Guardrails", **overrides):
    response = await client.post("/api/v1/sets", json={"name": name, **overrides})
    assert response.status_code == 201, response.text
    return response.json()


# -- CRUD ----------------------------------------------------------------------


async def test_create_and_read_a_case(client):
    created = await make_case(client)
    assert created["id"]
    assert created["title"] == "Say hello"
    assert created["tags"] == ["smoke"]
    assert created["sets"] == []

    fetched = await client.get(f"/api/v1/cases/{created['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == created["id"]


async def test_create_rejects_an_empty_title(client):
    response = await client.post("/api/v1/cases", json={**CASE, "title": ""})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_create_rejects_an_unknown_field(client):
    response = await client.post("/api/v1/cases", json={**CASE, "nonsense": 1})
    assert response.status_code == 422


async def test_create_can_attach_to_a_set_in_one_call(client):
    eval_set = await make_set(client)
    created = await make_case(client, set_id=eval_set["id"])
    assert [s["id"] for s in created["sets"]] == [eval_set["id"]]


async def test_create_with_an_unknown_set_is_404(client):
    response = await client.post("/api/v1/cases", json={**CASE, "set_id": 999})
    assert response.status_code == 404


async def test_get_unknown_case_is_404_with_the_envelope(client):
    response = await client.get("/api/v1/cases/999")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert "999" in response.json()["error"]["message"]


async def test_patch_updates_only_the_given_fields(client):
    case = await make_case(client, reference="original reference")
    response = await client.patch(f"/api/v1/cases/{case['id']}", json={"title": "Renamed"})
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Renamed"
    assert body["reference"] == "original reference"
    assert body["tags"] == ["smoke"]


async def test_patch_can_clear_a_nullable_field(client):
    case = await make_case(client, reference="something")
    response = await client.patch(f"/api/v1/cases/{case['id']}", json={"reference": None})
    assert response.json()["reference"] is None


async def test_patch_replaces_scoring_wholesale(client):
    case = await make_case(client)
    scoring = [{"type": "contains", "params": {"text": "hello"}, "required": True, "weight": 1}]
    response = await client.patch(f"/api/v1/cases/{case['id']}", json={"scoring": scoring})
    assert response.json()["scoring"][0]["type"] == "contains"


async def test_duplicate_creates_an_independent_copy(client):
    case = await make_case(client, reference="ref")
    response = await client.post(f"/api/v1/cases/{case['id']}/duplicate")
    assert response.status_code == 201
    copy = response.json()
    assert copy["id"] != case["id"]
    assert copy["title"] == "Say hello (copy)"
    assert copy["reference"] == "ref"

    await client.patch(f"/api/v1/cases/{copy['id']}", json={"title": "Diverged"})
    original = await client.get(f"/api/v1/cases/{case['id']}")
    assert original.json()["title"] == "Say hello"


# -- trash ---------------------------------------------------------------------


async def test_delete_moves_to_the_trash_and_restore_brings_it_back(client):
    case = await make_case(client)
    deleted = await client.delete(f"/api/v1/cases/{case['id']}")
    assert deleted.status_code == 200
    assert deleted.json()["message"] == "moved to trash"

    live = await client.get("/api/v1/cases")
    assert live.json() == []

    trashed = await client.get("/api/v1/cases", params={"trashed": True})
    assert len(trashed.json()) == 1
    assert trashed.json()[0]["deleted_at"] is not None

    restored = await client.post(f"/api/v1/cases/{case['id']}/restore")
    assert restored.status_code == 200
    assert restored.json()["deleted_at"] is None
    assert len((await client.get("/api/v1/cases")).json()) == 1


async def test_trashed_cases_cannot_be_edited(client):
    case = await make_case(client)
    await client.delete(f"/api/v1/cases/{case['id']}")
    response = await client.patch(f"/api/v1/cases/{case['id']}", json={"title": "x"})
    assert response.status_code == 404
    assert "trash" in response.json()["error"]["message"]


async def test_purge_removes_the_row_and_its_memberships(client):
    eval_set = await make_set(client)
    case = await make_case(client, set_id=eval_set["id"])
    response = await client.delete(f"/api/v1/cases/{case['id']}", params={"purge": True})
    assert response.json()["message"] == "purged"

    assert (await client.get(f"/api/v1/cases/{case['id']}")).status_code == 404
    set_cases = await client.get(f"/api/v1/sets/{eval_set['id']}/cases")
    assert set_cases.json() == []


# -- search & filter (F1.6) ----------------------------------------------------


async def test_free_text_search_covers_title_input_notes_and_reference(client):
    await make_case(client, title="Goroutine leak", tags=[])
    await make_case(client, title="Other", input=[{"role": "user", "content": "goroutine pool"}])
    await make_case(client, title="Third", notes="about goroutines")
    await make_case(client, title="Fourth", reference="goroutine reference")
    await make_case(client, title="Unrelated", tags=[])

    response = await client.get("/api/v1/cases", params={"q": "goroutine"})
    assert len(response.json()) == 4


async def test_tag_filter_requires_every_tag(client):
    await make_case(client, title="Both", tags=["go", "concurrency"])
    await make_case(client, title="One", tags=["go"])

    both = await client.get("/api/v1/cases", params={"tags": ["go", "concurrency"]})
    assert [c["title"] for c in both.json()] == ["Both"]

    single = await client.get("/api/v1/cases", params={"tags": ["go"]})
    assert len(single.json()) == 2


async def test_tag_filter_does_not_match_a_substring_of_another_tag(client):
    await make_case(client, title="Golang", tags=["golang"])
    response = await client.get("/api/v1/cases", params={"tags": ["go"]})
    assert response.json() == []


async def test_set_membership_filters(client):
    eval_set = await make_set(client)
    inside = await make_case(client, title="Inside", set_id=eval_set["id"])
    await make_case(client, title="Outside")

    in_set = await client.get("/api/v1/cases", params={"set_id": eval_set["id"]})
    assert [c["id"] for c in in_set.json()] == [inside["id"]]

    not_in_set = await client.get("/api/v1/cases", params={"exclude_set_id": eval_set["id"]})
    assert [c["title"] for c in not_in_set.json()] == ["Outside"]


async def test_pagination_reports_the_total_in_a_header(client):
    for i in range(5):
        await make_case(client, title=f"Case {i}")
    response = await client.get("/api/v1/cases", params={"limit": 2, "offset": 1})
    assert len(response.json()) == 2
    assert response.headers["X-Total-Count"] == "5"


async def test_empty_result_is_an_empty_list_not_an_error(client):
    response = await client.get("/api/v1/cases")
    assert response.status_code == 200
    assert response.json() == []
    assert response.headers["X-Total-Count"] == "0"


# -- bulk operations (F1.2) ----------------------------------------------------


async def test_bulk_add_and_remove_tags(client):
    a = await make_case(client, title="A", tags=["keep", "drop"])
    b = await make_case(client, title="B", tags=["drop"])

    response = await client.post(
        "/api/v1/cases/bulk/tags",
        json={"case_ids": [a["id"], b["id"]], "add_tags": ["new"], "remove_tags": ["drop"]},
    )
    assert response.json()["count"] == 2

    refreshed = await client.get("/api/v1/cases")
    tags = {c["title"]: c["tags"] for c in refreshed.json()}
    assert tags["A"] == ["keep", "new"]
    assert tags["B"] == ["new"]


async def test_bulk_tags_requires_something_to_do(client):
    case = await make_case(client)
    response = await client.post("/api/v1/cases/bulk/tags", json={"case_ids": [case["id"]]})
    assert response.status_code == 422


async def test_bulk_op_with_an_unknown_id_fails_loudly(client):
    case = await make_case(client)
    response = await client.post(
        "/api/v1/cases/bulk/tags", json={"case_ids": [case["id"], 999], "add_tags": ["x"]}
    )
    assert response.status_code == 404
    assert response.json()["error"]["details"]["missing"] == [999]


async def test_bulk_copy_leaves_the_source_set_intact(client):
    source = await make_set(client, name="Source")
    target = await make_set(client, name="Target")
    case = await make_case(client, set_id=source["id"])

    response = await client.post(
        "/api/v1/cases/bulk/move",
        json={"case_ids": [case["id"]], "target_set_id": target["id"], "mode": "copy"},
    )
    assert response.json()["count"] == 1
    assert len((await client.get(f"/api/v1/sets/{source['id']}/cases")).json()) == 1
    assert len((await client.get(f"/api/v1/sets/{target['id']}/cases")).json()) == 1


async def test_bulk_move_detaches_from_the_source_set(client):
    source = await make_set(client, name="Source")
    target = await make_set(client, name="Target")
    case = await make_case(client, set_id=source["id"])

    response = await client.post(
        "/api/v1/cases/bulk/move",
        json={
            "case_ids": [case["id"]],
            "target_set_id": target["id"],
            "source_set_id": source["id"],
            "mode": "move",
        },
    )
    assert response.status_code == 200
    assert (await client.get(f"/api/v1/sets/{source['id']}/cases")).json() == []
    assert len((await client.get(f"/api/v1/sets/{target['id']}/cases")).json()) == 1


async def test_bulk_move_without_a_source_set_is_rejected(client):
    target = await make_set(client, name="Target")
    case = await make_case(client)
    response = await client.post(
        "/api/v1/cases/bulk/move",
        json={"case_ids": [case["id"]], "target_set_id": target["id"], "mode": "move"},
    )
    assert response.status_code == 422
    assert "source_set_id" in response.json()["error"]["message"]


async def test_bulk_move_is_idempotent_for_cases_already_in_the_target(client):
    target = await make_set(client, name="Target")
    case = await make_case(client, set_id=target["id"])
    await client.post(
        "/api/v1/cases/bulk/move",
        json={"case_ids": [case["id"]], "target_set_id": target["id"], "mode": "copy"},
    )
    assert len((await client.get(f"/api/v1/sets/{target['id']}/cases")).json()) == 1


async def test_bulk_delete_restore_and_purge(client):
    a = await make_case(client, title="A")
    b = await make_case(client, title="B")
    ids = [a["id"], b["id"]]

    deleted = await client.post("/api/v1/cases/bulk/delete", json={"case_ids": ids})
    assert deleted.status_code == 200
    assert deleted.json()["count"] == 2
    assert (await client.get("/api/v1/cases")).json() == []

    restored = await client.post("/api/v1/cases/bulk/restore", json={"case_ids": ids})
    assert restored.status_code == 200
    assert restored.json()["count"] == 2
    assert len((await client.get("/api/v1/cases")).json()) == 2

    await client.post("/api/v1/cases/bulk/delete", json={"case_ids": ids})
    purged = await client.post("/api/v1/cases/bulk/purge", json={"case_ids": ids})
    assert purged.status_code == 200
    assert purged.json()["count"] == 2
    assert (await client.get("/api/v1/cases", params={"trashed": True})).json() == []


@pytest.mark.parametrize("op", ["tags", "move", "delete", "restore", "purge"])
async def test_bulk_routes_are_not_shadowed_by_the_id_route(client, op):
    """`/cases/bulk/<op>` must not be parsed as `/cases/{case_id}/…`.

    FastAPI matches in declaration order, so the literal routes have to come
    first; without that these all 422 on `case_id="bulk"`.
    """
    case = await make_case(client)
    target = await make_set(client, name="Bulk target")
    payload = {"case_ids": [case["id"]]}
    if op == "tags":
        payload["add_tags"] = ["x"]
    if op == "move":
        payload["target_set_id"] = target["id"]
    if op in {"restore", "purge"}:
        await client.delete(f"/api/v1/cases/{case['id']}")

    response = await client.post(f"/api/v1/cases/bulk/{op}", json=payload)
    assert response.status_code == 200, response.text


async def test_bulk_ops_refuse_trashed_cases(client):
    case = await make_case(client)
    await client.delete(f"/api/v1/cases/{case['id']}")
    response = await client.post(
        "/api/v1/cases/bulk/tags", json={"case_ids": [case["id"]], "add_tags": ["x"]}
    )
    assert response.status_code == 422
    assert "trash" in response.json()["error"]["message"]


# -- import / export (F1.3) ----------------------------------------------------


def jsonl(*objs):
    return "".join(json.dumps(o) + "\n" for o in objs)


VALID_ROW = {"title": "Imported", "input": [{"role": "user", "content": "x"}], "tags": ["imp"]}


async def test_import_creates_cases(client):
    response = await client.post(
        "/api/v1/cases/import",
        json={"content": jsonl(VALID_ROW, {**VALID_ROW, "title": "Second"}), "format": "jsonl"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["imported"] == 2
    assert len(body["case_ids"]) == 2
    assert len((await client.get("/api/v1/cases")).json()) == 2


async def test_import_is_atomic_one_bad_row_writes_nothing(client):
    content = jsonl(VALID_ROW) + "{broken}\n" + jsonl({**VALID_ROW, "title": "Third"})
    response = await client.post(
        "/api/v1/cases/import", json={"content": content, "format": "jsonl"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["imported"] == 0
    assert [e["line"] for e in body["errors"]] == [2]
    assert (await client.get("/api/v1/cases")).json() == [], "nothing may be written"


async def test_import_dry_run_validates_without_writing(client):
    response = await client.post(
        "/api/v1/cases/import",
        json={"content": jsonl(VALID_ROW), "format": "jsonl", "dry_run": True},
    )
    assert response.json() == {
        "ok": True,
        "imported": 1,
        "errors": [],
        "warnings": [],
        "case_ids": [],
        "dry_run": True,
    }
    assert (await client.get("/api/v1/cases")).json() == []


async def test_import_into_a_set_preserves_file_order(client):
    eval_set = await make_set(client)
    content = jsonl(
        {**VALID_ROW, "title": "First"},
        {**VALID_ROW, "title": "Second"},
        {**VALID_ROW, "title": "Third"},
    )
    await client.post(
        "/api/v1/cases/import",
        json={"content": content, "format": "jsonl", "set_id": eval_set["id"]},
    )
    cases = (await client.get(f"/api/v1/sets/{eval_set['id']}/cases")).json()
    assert [c["title"] for c in cases] == ["First", "Second", "Third"]
    assert [c["position"] for c in cases] == [0, 1, 2]


async def test_import_into_an_unknown_set_is_404(client):
    response = await client.post(
        "/api/v1/cases/import", json={"content": jsonl(VALID_ROW), "set_id": 999}
    )
    assert response.status_code == 404


async def test_import_yaml(client):
    content = "cases:\n  - title: From YAML\n    input:\n      - role: user\n        content: hi\n"
    response = await client.post(
        "/api/v1/cases/import", json={"content": content, "format": "yaml"}
    )
    assert response.json()["imported"] == 1


async def test_import_from_an_uploaded_file_infers_the_format(client):
    files = {"file": ("cases.jsonl", jsonl(VALID_ROW).encode(), "application/x-ndjson")}
    response = await client.post("/api/v1/cases/import/file", files=files)
    assert response.status_code == 200
    assert response.json()["imported"] == 1


async def test_import_rejects_a_non_utf8_file(client):
    files = {"file": ("cases.jsonl", b"\xff\xfe\x00binary", "application/octet-stream")}
    response = await client.post("/api/v1/cases/import/file", files=files)
    assert response.status_code == 422
    assert "UTF-8" in response.json()["error"]["message"]


@pytest.mark.parametrize("fmt", ["jsonl", "yaml", "json"])
async def test_export_import_round_trip_is_identical(client, fmt):
    """G1's authoritative flow: create → export → reimport → identical."""
    eval_set = await make_set(client, name="Round trip")
    originals = [
        {
            "title": "Guardrail block",
            "input": [{"role": "user", "content": "make napalm"}],
            "reference": "must block",
            "scoring": [
                {
                    "type": "contains",
                    "params": {"text": '"action": "block"', "case_sensitive": False},
                    "required": True,
                    "weight": 1,
                }
            ],
            "tags": ["guardrail", "jailbreak"],
            "notes": "release blocker",
        },
        {
            "title": "Benign lookalike",
            "input": [
                {"role": "system", "content": "You are a guardrail."},
                {"role": "user", "content": "chemistry homework help"},
            ],
            "reference": None,
            "scoring": [],
            "tags": ["guardrail"],
            "notes": None,
        },
        {"title": "Third", "input": [{"role": "user", "content": "x"}]},
    ]
    imported = await client.post(
        "/api/v1/cases/import",
        json={"content": jsonl(*originals), "format": "jsonl", "set_id": eval_set["id"]},
    )
    assert imported.json()["imported"] == 3

    exported = await client.get(
        "/api/v1/cases/export", params={"set_id": eval_set["id"], "format": fmt}
    )
    assert exported.status_code == 200
    payload = exported.text

    # Wipe and reimport from the export alone.
    ids = imported.json()["case_ids"]
    await client.post("/api/v1/cases/bulk/delete", json={"case_ids": ids})
    await client.post("/api/v1/cases/bulk/purge", json={"case_ids": ids})
    assert (await client.get("/api/v1/cases")).json() == []

    reimported = await client.post(
        "/api/v1/cases/import",
        json={"content": payload, "format": fmt, "set_id": eval_set["id"]},
    )
    assert reimported.json()["imported"] == 3

    reexported = await client.get(
        "/api/v1/cases/export", params={"set_id": eval_set["id"], "format": fmt}
    )
    assert reexported.text == payload, "a second round trip must be byte-identical"


async def test_export_sets_a_download_filename(client):
    await make_case(client)
    response = await client.get("/api/v1/cases/export")
    assert "attachment" in response.headers["content-disposition"]
    assert "gaugix-cases.jsonl" in response.headers["content-disposition"]


async def test_export_can_be_inline_for_preview(client):
    await make_case(client)
    response = await client.get("/api/v1/cases/export", params={"download": False})
    assert "content-disposition" not in response.headers


async def test_export_excludes_trashed_cases(client):
    keep = await make_case(client, title="Keep")
    drop = await make_case(client, title="Drop")
    await client.delete(f"/api/v1/cases/{drop['id']}")

    response = await client.get("/api/v1/cases/export")
    assert "Keep" in response.text
    assert "Drop" not in response.text
    assert keep["id"]


# -- foreign formats (PRD F1.3, extended) --------------------------------------


async def test_importing_a_csv_lands_real_cases(client):
    eval_set = await make_set(client, name="From CSV")
    response = await client.post(
        "/api/v1/cases/import",
        json={
            "content": "question,answer\nWhat is 2+2?,4\nCapital of France?,Paris\n",
            "format": "csv",
            "set_id": eval_set["id"],
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["imported"] == 2
    cases = (await client.get(f"/api/v1/sets/{eval_set['id']}/cases")).json()
    assert [c["reference"] for c in cases] == ["4", "Paris"]


async def test_a_csv_with_unguessable_columns_writes_nothing_and_says_why(client):
    response = await client.post(
        "/api/v1/cases/import",
        json={"content": "col_a,col_b\nfoo,bar\n", "format": "csv"},
    )

    body = response.json()
    assert body["ok"] is False and body["imported"] == 0
    assert "mapping.input" in body["errors"][0]["message"]
    assert (await client.get("/api/v1/cases")).json() == []


async def test_an_explicit_mapping_overrides_the_guess(client):
    response = await client.post(
        "/api/v1/cases/import",
        json={
            "content": "col_a,col_b\nask this,expect that\n",
            "format": "csv",
            "mapping": {"input": "col_a", "reference": "col_b", "title_prefix": "Row"},
        },
    )

    assert response.json()["imported"] == 1
    case = (await client.get("/api/v1/cases")).json()[0]
    assert case["input"][0]["content"] == "ask this"
    assert case["reference"] == "expect that"


async def test_promptfoo_import_reports_what_it_could_not_translate(client):
    config = """
tests:
  - description: scripted
    vars: {input: "hello"}
    assert:
      - type: javascript
        value: "output.length > 3"
      - type: contains
        value: "hell"
"""
    response = await client.post(
        "/api/v1/cases/import", json={"content": config, "format": "promptfoo"}
    )

    body = response.json()
    # Warnings never block: the case is worth having, the missing check is
    # worth knowing about.
    assert body["ok"] is True and body["imported"] == 1
    assert len(body["warnings"]) == 1
    assert "javascript" in body["warnings"][0]["message"]

    case = (await client.get("/api/v1/cases")).json()[0]
    assert [s["type"] for s in case["scoring"]] == ["contains"]


async def test_cases_export_to_csv_and_come_back_in(client):
    await client.post(
        "/api/v1/cases",
        json={
            "title": "Roundtrip",
            "input": [{"role": "user", "content": "2+2?"}],
            "reference": "4",
        },
    )

    exported = await client.get("/api/v1/cases/export", params={"format": "csv"})
    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("text/csv")

    reimported = await client.post(
        "/api/v1/cases/import", json={"content": exported.text, "format": "csv"}
    )
    assert reimported.json()["imported"] == 1
    titles = [c["title"] for c in (await client.get("/api/v1/cases")).json()]
    assert titles.count("Roundtrip") == 2


async def test_openai_evals_export_is_readable_by_the_openai_evals_importer(client):
    await client.post(
        "/api/v1/cases",
        json={"title": "Evals", "input": [{"role": "user", "content": "2+2?"}], "reference": "4"},
    )

    exported = await client.get("/api/v1/cases/export", params={"format": "openai_evals"})
    payload = json.loads(exported.text.splitlines()[0])

    assert payload["input"] == [{"role": "user", "content": "2+2?"}]
    assert payload["ideal"] == "4"


async def test_unfiled_finds_cases_that_belong_to_no_set(client):
    """A case removed from a set but not deleted was unreachable in the UI.

    Every listing was scoped to a set, so it existed, took up an id, and could
    not be found again.
    """
    eval_set = await make_set(client, name="Somewhere")
    filed = await make_case(client, title="Filed", set_id=eval_set["id"])
    orphan = await make_case(client, title="Orphan")

    unfiled = await client.get("/api/v1/cases", params={"unfiled": True})

    assert [c["title"] for c in unfiled.json()] == ["Orphan"]

    # Detaching the filed one makes it unfiled too, without deleting it.
    detached = await client.post(
        f"/api/v1/sets/{eval_set['id']}/cases/detach", json={"case_ids": [filed["id"]]}
    )
    assert detached.status_code == 200, detached.text
    again = await client.get("/api/v1/cases", params={"unfiled": True})
    assert sorted(c["id"] for c in again.json()) == sorted([filed["id"], orphan["id"]])
