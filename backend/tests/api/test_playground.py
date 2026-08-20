"""Manual Playground uses an executor without manufacturing a formal run."""

from __future__ import annotations

from sqlmodel import select

from gaugix.models.runs import Attempt, Run, RunItem
from tests.api.test_runs import make_fake_stack


async def test_playground_returns_text_structured_output_usage_and_transcript(client, session):
    stack = await make_fake_stack(
        client,
        harness_config={
            "mode": "script",
            "script": [{"match": "classify", "response": '{"label":"positive","score":0.8}'}],
        },
    )
    response = await client.post(
        "/api/v1/playground/invoke",
        json={
            "executor_id": stack["executor"]["id"],
            "messages": [
                {"role": "system", "content": "Return JSON"},
                {"role": "user", "content": "classify this"},
            ],
            "params": {"temperature": 0},
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert body["parsed_output"] == {"label": "positive", "score": 0.8}
    assert body["messages"][-1]["role"] == "assistant"
    assert body["usage"]["cost_usd"] == 0
    assert body["raw"]["harness"] == "fake"

    assert session.exec(select(Run)).all() == []
    assert session.exec(select(RunItem)).all() == []
    assert session.exec(select(Attempt)).all() == []


async def test_playground_surfaces_harness_errors_as_an_inspectable_result(client):
    stack = await make_fake_stack(
        client,
        harness_config={
            "fail_if_contains": "explode",
            "error_message": "manual probe failed",
            "error_retryable": False,
        },
    )
    response = await client.post(
        "/api/v1/playground/invoke",
        json={
            "executor_id": stack["executor"]["id"],
            "messages": [{"role": "user", "content": "explode"}],
        },
    )
    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert response.json()["error_kind"] == "injected"
    assert "manual probe failed" in response.json()["error"]


async def test_playground_rejects_unknown_executor_and_empty_conversation(client):
    unknown = await client.post(
        "/api/v1/playground/invoke",
        json={"executor_id": 999, "messages": [{"role": "user", "content": "hi"}]},
    )
    assert unknown.status_code == 404
    empty = await client.post(
        "/api/v1/playground/invoke", json={"executor_id": 999, "messages": []}
    )
    assert empty.status_code == 422
