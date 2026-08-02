"""Generation-prompt builder (PRD F1.4 path A)."""

from __future__ import annotations

import json
from typing import Any

from gaugix.api.gen import build_generation_prompt
from tests.api.test_cases import make_case, make_set


def test_prompt_states_the_topic_and_count():
    prompt = build_generation_prompt("prompt injection", 12, examples=[])
    assert "prompt injection" in prompt
    assert "Write 12 new eval cases" in prompt
    assert "Output exactly 12 lines" in prompt


def test_prompt_carries_the_canonical_schema_and_scorer_menu():
    prompt = build_generation_prompt("x", 3, examples=[])
    for field in ("title", "input", "reference", "scoring", "tags", "notes"):
        assert f'"{field}"' in prompt
    for scorer in ("contains", "regex", "json_schema", "llm_judge", "human"):
        assert scorer in prompt


def test_prompt_demands_bare_jsonl():
    prompt = build_generation_prompt("x", 3, examples=[])
    assert "JSONL only" in prompt
    assert "no markdown fence" in prompt


def test_examples_are_embedded_as_jsonl():
    example: dict[str, Any] = {
        "title": "Sample",
        "input": [{"role": "user", "content": "hi"}],
        "tags": ["t"],
    }
    prompt = build_generation_prompt("x", 2, examples=[example])
    assert json.dumps(example, ensure_ascii=False) in prompt
    assert "Examples from the author's existing set (1)" in prompt


def test_no_example_section_when_there_are_none():
    assert "Examples from the author" not in build_generation_prompt("x", 2, examples=[])


def test_author_instructions_are_included():
    prompt = build_generation_prompt("x", 2, examples=[], instructions="Use Simplified Chinese.")
    assert "Use Simplified Chinese." in prompt


async def test_endpoint_seeds_examples_from_the_set(client):
    eval_set = await make_set(client, name="Guardrails")
    first = await make_case(client, title="Injection A", set_id=eval_set["id"])
    await make_case(client, title="Injection B", set_id=eval_set["id"])
    await make_case(client, title="Injection C", set_id=eval_set["id"])

    response = await client.post(
        "/api/v1/gen/prompt",
        json={
            "topic": "obfuscated jailbreaks",
            "count": 8,
            "set_id": eval_set["id"],
            "example_count": 2,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert "obfuscated jailbreaks" in body["prompt"]
    assert "Guardrails" in body["prompt"]
    assert len(body["example_case_ids"]) == 2
    assert body["example_case_ids"][0] == first["id"], "examples follow set order"


async def test_endpoint_works_without_a_set(client):
    response = await client.post("/api/v1/gen/prompt", json={"topic": "translation quality"})
    assert response.status_code == 200
    assert response.json()["example_case_ids"] == []


async def test_endpoint_rejects_an_empty_topic(client):
    assert (await client.post("/api/v1/gen/prompt", json={"topic": ""})).status_code == 422


async def test_endpoint_with_an_unknown_set_is_404(client):
    response = await client.post("/api/v1/gen/prompt", json={"topic": "x", "set_id": 999})
    assert response.status_code == 404


async def test_generated_jsonl_round_trips_through_import(client):
    """The generated prompt's schema and the importer must agree."""
    eval_set = await make_set(client, name="Round")
    await make_case(client, title="Example", set_id=eval_set["id"], tags=["seed"])

    prompt = (
        await client.post(
            "/api/v1/gen/prompt", json={"topic": "x", "set_id": eval_set["id"], "example_count": 1}
        )
    ).json()["prompt"]

    # Pull the embedded example back out of the prompt and re-import it.
    embedded = next(line for line in prompt.splitlines() if line.startswith('{"title": "Example"'))
    response = await client.post("/api/v1/cases/import", json={"content": embedded + "\n"})
    assert response.json()["ok"] is True, response.json()


async def test_direct_generation_returns_candidates_without_writing_them(client):
    """Path B is a draft, not a commit — the same gate as a pasted file.

    A model's output gets no more trust than a stranger's JSONL, so it comes
    back for review and goes in through the ordinary import validator.
    """
    from tests.api.test_runs import make_fake_stack

    lines = "\n".join(
        json.dumps({"title": f"Generated {i}", "input": [{"role": "user", "content": "hi"}]})
        for i in range(1, 4)
    )
    stack = await make_fake_stack(client, "author", {"mode": "script", "default_response": lines})

    response = await client.post(
        "/api/v1/gen/direct",
        json={"topic": "guardrails", "count": 3, "executor_id": stack["executor"]["id"]},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert [c["title"] for c in body["cases"]] == ["Generated 1", "Generated 2", "Generated 3"]
    assert body["errors"] == []
    assert body["usage"]["executor"] == stack["executor"]["name"]
    # Nothing was written: committing is a separate, explicit import.
    assert (await client.get("/api/v1/cases")).json() == []


async def test_direct_generation_reports_the_rows_the_model_got_wrong(client):
    from tests.api.test_runs import make_fake_stack

    stack = await make_fake_stack(
        client,
        "sloppy",
        {"mode": "script", "default_response": '{"title": "ok", "input": []}\nnot json at all'},
    )

    body = (
        await client.post(
            "/api/v1/gen/direct",
            json={"topic": "x", "count": 2, "executor_id": stack["executor"]["id"]},
        )
    ).json()

    assert [e["line"] for e in body["errors"]] == [2]
    # The raw text is kept so a mangled response can be read rather than guessed at.
    assert "not json at all" in body["raw_output"]


async def test_direct_generation_strips_the_code_fence_models_keep_adding(client):
    from tests.api.test_runs import make_fake_stack

    fenced = '```json\n{"title": "Fenced", "input": [{"role": "user", "content": "hi"}]}\n```'
    stack = await make_fake_stack(client, "fencer", {"mode": "script", "default_response": fenced})

    body = (
        await client.post(
            "/api/v1/gen/direct",
            json={"topic": "x", "count": 1, "executor_id": stack["executor"]["id"]},
        )
    ).json()

    assert [c["title"] for c in body["cases"]] == ["Fenced"]


async def test_direct_generation_with_an_unknown_executor_is_a_404(client):
    response = await client.post(
        "/api/v1/gen/direct", json={"topic": "x", "count": 1, "executor_id": 999}
    )
    assert response.status_code == 404
