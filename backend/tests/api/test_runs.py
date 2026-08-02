"""Run API: builder, lifecycle, item board, drill-down, SSE, settings."""

from __future__ import annotations

import asyncio

from tests.api.test_cases import make_case, make_set


async def make_fake_stack(client, name="fake", harness_config=None):
    """Create a fake model + harness + executor via the public API."""
    model = await client.post(
        "/api/v1/model-profiles",
        json={"name": f"{name}-model", "provider": "fake", "model_id": name},
    )
    assert model.status_code == 201, model.text
    harness = await client.post(
        "/api/v1/harness-profiles",
        json={"name": f"{name}-harness", "kind": "fake", "config": harness_config or {}},
    )
    assert harness.status_code == 201, harness.text
    executor = await client.post(
        "/api/v1/executors",
        json={
            "model_profile_id": model.json()["id"],
            "harness_profile_id": harness.json()["id"],
        },
    )
    assert executor.status_code == 201, executor.text
    return {
        "model": model.json(),
        "harness": harness.json(),
        "executor": executor.json(),
    }


async def seeded_set(client, n=3):
    eval_set = await make_set(client, name="Run set")
    for i in range(n):
        await make_case(client, title=f"Case {i}", set_id=eval_set["id"])
    return eval_set


async def wait_for_run(client, run_id, deadline_s=10.0):
    """Poll until the run leaves the active states."""
    deadline = asyncio.get_running_loop().time() + deadline_s
    while asyncio.get_running_loop().time() < deadline:
        response = await client.get(f"/api/v1/runs/{run_id}")
        body = response.json()
        if body["status"] in {"completed", "failed", "canceled", "interrupted"}:
            return body
        await asyncio.sleep(0.05)
    raise AssertionError(f"run {run_id} did not finish within {deadline_s}s")


# -- model / harness / executor CRUD -------------------------------------------


async def test_executor_display_key_defaults_to_model_at_harness(client):
    stack = await make_fake_stack(client)
    assert stack["executor"]["name"] == "fake-model @ fake-harness"


async def test_executor_name_can_be_overridden(client):
    model = (
        await client.post(
            "/api/v1/model-profiles", json={"name": "m1", "provider": "fake", "model_id": "m1"}
        )
    ).json()
    harness = (
        await client.post("/api/v1/harness-profiles", json={"name": "h1", "kind": "fake"})
    ).json()
    response = await client.post(
        "/api/v1/executors",
        json={
            "name": "my custom key",
            "model_profile_id": model["id"],
            "harness_profile_id": harness["id"],
        },
    )
    assert response.json()["name"] == "my custom key"


async def test_model_profile_names_are_unique(client):
    await client.post(
        "/api/v1/model-profiles", json={"name": "dup", "provider": "fake", "model_id": "x"}
    )
    again = await client.post(
        "/api/v1/model-profiles", json={"name": "dup", "provider": "fake", "model_id": "x"}
    )
    assert again.status_code == 409


async def test_non_fake_provider_requires_a_model_id(client):
    response = await client.post(
        "/api/v1/model-profiles", json={"name": "m", "provider": "anthropic", "model_id": ""}
    )
    assert response.status_code == 422
    assert "model_id" in response.json()["error"]["message"]


async def test_openai_compatible_requires_a_base_url(client):
    response = await client.post(
        "/api/v1/model-profiles",
        json={"name": "m", "provider": "openai_compatible", "model_id": "some/model"},
    )
    assert response.status_code == 422
    assert "base_url" in response.json()["error"]["message"]


async def test_model_profile_never_echoes_a_key(client):
    response = await client.post(
        "/api/v1/model-profiles",
        json={
            "name": "gw",
            "provider": "openai_compatible",
            "model_id": "x",
            "base_url": "https://example.test/v1",
            "api_key_env": "SOME_KEY_ENV",
        },
    )
    body = response.json()
    assert body["api_key_env"] == "SOME_KEY_ENV"
    assert "api_key" not in body
    assert body["key_present"] is False, "the env var is not set in tests"


async def test_cli_harness_requires_a_prompt_file_placeholder(client):
    response = await client.post(
        "/api/v1/harness-profiles",
        json={"name": "cli1", "kind": "cli", "config": {"command_template": "run --now"}},
    )
    assert response.status_code == 422
    assert "{prompt_file}" in response.json()["error"]["message"]


async def test_fake_harness_rejects_an_unknown_mode(client):
    response = await client.post(
        "/api/v1/harness-profiles",
        json={"name": "bad", "kind": "fake", "config": {"mode": "telepathy"}},
    )
    assert response.status_code == 422


async def test_test_connection_on_a_fake_profile_is_free_and_simulated(client):
    stack = await make_fake_stack(client)
    response = await client.post(f"/api/v1/model-profiles/{stack['model']['id']}/test")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["cost_usd"] == 0.0
    assert body["prompt_tokens"] >= 1
    assert "ok" in body["output_preview"].lower()


async def test_test_connection_without_a_key_explains_what_to_set(client):
    model = (
        await client.post(
            "/api/v1/model-profiles",
            json={"name": "real", "provider": "anthropic", "model_id": "claude-haiku"},
        )
    ).json()
    response = await client.post(f"/api/v1/model-profiles/{model['id']}/test")
    body = response.json()
    assert body["ok"] is False
    assert body["error_kind"] == "missing_key"
    assert "ANTHROPIC_API_KEY" in body["message"]


async def test_executor_with_runs_is_archived_not_deleted(client):
    stack = await make_fake_stack(client)
    eval_set = await seeded_set(client, n=1)
    run = await client.post(
        "/api/v1/runs",
        json={"set_ids": [eval_set["id"]], "executor_ids": [stack["executor"]["id"]]},
    )
    await wait_for_run(client, run.json()["id"])

    response = await client.delete(f"/api/v1/executors/{stack['executor']['id']}")
    assert response.json()["message"] == "archived (has runs)"
    assert (await client.get(f"/api/v1/executors/{stack['executor']['id']}")).json()["archived"]


async def test_unused_executor_is_deleted_outright(client):
    stack = await make_fake_stack(client)
    response = await client.delete(f"/api/v1/executors/{stack['executor']['id']}")
    assert response.json()["message"] == "deleted"
    assert (await client.get(f"/api/v1/executors/{stack['executor']['id']}")).status_code == 404


# -- run builder ---------------------------------------------------------------


async def test_preview_reports_the_matrix_size(client):
    stack_a = await make_fake_stack(client, "a")
    stack_b = await make_fake_stack(client, "b")
    eval_set = await seeded_set(client, n=4)

    response = await client.post(
        "/api/v1/runs/preview",
        json={
            "set_ids": [eval_set["id"]],
            "executor_ids": [stack_a["executor"]["id"], stack_b["executor"]["id"]],
        },
    )
    body = response.json()
    assert body["case_count"] == 4
    assert body["executor_count"] == 2
    assert body["item_count"] == 8
    assert body["suggested_name"]


async def test_preview_of_nothing_is_zero_not_an_error(client):
    response = await client.post("/api/v1/runs/preview", json={})
    assert response.status_code == 200
    assert response.json()["item_count"] == 0


async def test_estimated_cost_is_zero_for_fake_executors(client):
    stack = await make_fake_stack(client)
    eval_set = await seeded_set(client)
    response = await client.post(
        "/api/v1/runs/preview",
        json={"set_ids": [eval_set["id"]], "executor_ids": [stack["executor"]["id"]]},
    )
    assert response.json()["estimated_cost_usd"] == 0.0


async def test_estimated_cost_is_null_when_pricing_is_unknown(client):
    """Half an estimate is worse than none — it reads as "this run is cheap"."""
    model = (
        await client.post(
            "/api/v1/model-profiles",
            json={"name": "unpriced", "provider": "anthropic", "model_id": "claude-x"},
        )
    ).json()
    harness = (
        await client.post("/api/v1/harness-profiles", json={"name": "direct1", "kind": "direct"})
    ).json()
    executor = (
        await client.post(
            "/api/v1/executors",
            json={"model_profile_id": model["id"], "harness_profile_id": harness["id"]},
        )
    ).json()
    eval_set = await seeded_set(client)

    response = await client.post(
        "/api/v1/runs/preview",
        json={"set_ids": [eval_set["id"]], "executor_ids": [executor["id"]]},
    )
    assert response.json()["estimated_cost_usd"] is None


async def test_estimated_cost_uses_a_pricing_override(client):
    model = (
        await client.post(
            "/api/v1/model-profiles",
            json={
                "name": "priced",
                "provider": "anthropic",
                "model_id": "claude-haiku",
                "pricing": {"input_per_1m": 1.0, "output_per_1m": 5.0},
            },
        )
    ).json()
    harness = (
        await client.post("/api/v1/harness-profiles", json={"name": "direct2", "kind": "direct"})
    ).json()
    executor = (
        await client.post(
            "/api/v1/executors",
            json={"model_profile_id": model["id"], "harness_profile_id": harness["id"]},
        )
    ).json()
    eval_set = await seeded_set(client, n=10)

    response = await client.post(
        "/api/v1/runs/preview",
        json={"set_ids": [eval_set["id"]], "executor_ids": [executor["id"]]},
    )
    # 10 cases × (400 × $1 + 400 × $5) per 1M tokens = 10 × 0.0024
    assert response.json()["estimated_cost_usd"] == 0.024


# -- run lifecycle -------------------------------------------------------------


async def test_run_executes_to_completion(client):
    stack = await make_fake_stack(client)
    eval_set = await seeded_set(client, n=3)

    created = await client.post(
        "/api/v1/runs",
        json={"set_ids": [eval_set["id"]], "executor_ids": [stack["executor"]["id"]]},
    )
    assert created.status_code == 201
    run = await wait_for_run(client, created.json()["id"])

    assert run["status"] == "completed"
    assert run["totals"]["items"] == 3
    assert run["totals"]["passed"] == 3


async def test_run_can_be_planned_without_starting(client):
    stack = await make_fake_stack(client)
    eval_set = await seeded_set(client, n=2)

    created = await client.post(
        "/api/v1/runs",
        json={
            "set_ids": [eval_set["id"]],
            "executor_ids": [stack["executor"]["id"]],
            "start": False,
        },
    )
    body = created.json()
    assert body["status"] == "pending"
    assert body["is_resumable"] is True

    items = await client.get(f"/api/v1/runs/{body['id']}/items")
    assert len(items.json()) == 2
    assert all(i["status"] == "pending" for i in items.json())


async def test_a_pending_run_can_be_resumed_into_execution(client):
    stack = await make_fake_stack(client)
    eval_set = await seeded_set(client, n=2)
    run = (
        await client.post(
            "/api/v1/runs",
            json={
                "set_ids": [eval_set["id"]],
                "executor_ids": [stack["executor"]["id"]],
                "start": False,
            },
        )
    ).json()

    resumed = await client.post(f"/api/v1/runs/{run['id']}/resume", json={})
    assert resumed.json()["ok"] is True
    assert resumed.json()["scheduled"] == 2

    finished = await wait_for_run(client, run["id"])
    assert finished["status"] == "completed"


async def test_resuming_a_finished_run_says_there_is_nothing_to_do(client):
    stack = await make_fake_stack(client)
    eval_set = await seeded_set(client, n=1)
    run = (
        await client.post(
            "/api/v1/runs",
            json={"set_ids": [eval_set["id"]], "executor_ids": [stack["executor"]["id"]]},
        )
    ).json()
    await wait_for_run(client, run["id"])

    response = await client.post(f"/api/v1/runs/{run['id']}/resume", json={})
    assert response.json()["ok"] is False
    assert "nothing to resume" in response.json()["message"]


async def test_run_with_a_failing_executor_records_item_errors(client):
    stack = await make_fake_stack(
        client, "boom", {"error_rate": 1.0, "error_message": "provider is down"}
    )
    eval_set = await seeded_set(client, n=2)
    run = (
        await client.post(
            "/api/v1/runs",
            json={"set_ids": [eval_set["id"]], "executor_ids": [stack["executor"]["id"]]},
        )
    ).json()
    finished = await wait_for_run(client, run["id"])

    assert finished["status"] == "completed", "item errors do not fail the run itself"
    assert finished["totals"]["error"] == 2

    items = (await client.get(f"/api/v1/runs/{run['id']}/items")).json()
    assert all("provider is down" in i["error"] for i in items)


async def test_run_builder_rejects_an_empty_set(client):
    stack = await make_fake_stack(client)
    empty = await make_set(client, name="Empty set")
    response = await client.post(
        "/api/v1/runs",
        json={"set_ids": [empty["id"]], "executor_ids": [stack["executor"]["id"]]},
    )
    assert response.status_code == 422
    assert "no cases" in response.json()["error"]["message"]


async def test_run_deletion_removes_items_and_attempts(client):
    stack = await make_fake_stack(client)
    eval_set = await seeded_set(client, n=2)
    run = (
        await client.post(
            "/api/v1/runs",
            json={"set_ids": [eval_set["id"]], "executor_ids": [stack["executor"]["id"]]},
        )
    ).json()
    await wait_for_run(client, run["id"])

    deleted = await client.delete(f"/api/v1/runs/{run['id']}")
    assert deleted.json()["ok"] is True
    assert (await client.get(f"/api/v1/runs/{run['id']}")).status_code == 404


# -- item board & drill-down ---------------------------------------------------


async def test_item_board_is_filterable(client):
    stack_a = await make_fake_stack(client, "a")
    stack_b = await make_fake_stack(client, "b")
    eval_set = await seeded_set(client, n=3)
    run = (
        await client.post(
            "/api/v1/runs",
            json={
                "set_ids": [eval_set["id"]],
                "executor_ids": [stack_a["executor"]["id"], stack_b["executor"]["id"]],
            },
        )
    ).json()
    await wait_for_run(client, run["id"])

    all_items = await client.get(f"/api/v1/runs/{run['id']}/items")
    assert len(all_items.json()) == 6
    assert all_items.headers["X-Total-Count"] == "6"

    one_lane = await client.get(
        f"/api/v1/runs/{run['id']}/items",
        params={"executor_key": stack_a["executor"]["name"]},
    )
    assert len(one_lane.json()) == 3

    by_status = await client.get(f"/api/v1/runs/{run['id']}/items", params={"status": ["passed"]})
    assert len(by_status.json()) == 6

    by_text = await client.get(f"/api/v1/runs/{run['id']}/items", params={"q": "Case 1"})
    assert len(by_text.json()) == 2


async def test_item_drill_down_shows_input_output_and_attempts(client):
    stack = await make_fake_stack(client)
    eval_set = await seeded_set(client, n=1)
    run = (
        await client.post(
            "/api/v1/runs",
            json={"set_ids": [eval_set["id"]], "executor_ids": [stack["executor"]["id"]]},
        )
    ).json()
    await wait_for_run(client, run["id"])

    item_id = (await client.get(f"/api/v1/runs/{run['id']}/items")).json()[0]["id"]
    detail = (await client.get(f"/api/v1/items/{item_id}")).json()

    assert detail["input"][0]["role"] == "user"
    assert detail["case_snapshot"]["title"] == "Case 0"
    assert len(detail["attempts"]) == 1
    attempt = detail["attempts"][0]
    assert attempt["n"] == 1
    assert attempt["status"] == "ok"
    assert attempt["output_text"]
    assert attempt["prompt_tokens"] > 0
    assert attempt["cost_usd"] == 0.0


async def test_unknown_item_is_404(client):
    assert (await client.get("/api/v1/items/999")).status_code == 404


# -- baselines -----------------------------------------------------------------


async def test_a_set_has_exactly_one_baseline_run(client):
    stack = await make_fake_stack(client)
    eval_set = await seeded_set(client, n=1)

    first = (
        await client.post(
            "/api/v1/runs",
            json={"set_ids": [eval_set["id"]], "executor_ids": [stack["executor"]["id"]]},
        )
    ).json()
    await wait_for_run(client, first["id"])
    second = (
        await client.post(
            "/api/v1/runs",
            json={"set_ids": [eval_set["id"]], "executor_ids": [stack["executor"]["id"]]},
        )
    ).json()
    await wait_for_run(client, second["id"])

    await client.post(f"/api/v1/runs/{first['id']}/baseline", json={"set_ids": [eval_set["id"]]})
    marked = await client.post(
        f"/api/v1/runs/{second['id']}/baseline", json={"set_ids": [eval_set["id"]]}
    )
    assert marked.json()["is_baseline_for"] == [eval_set["id"]]

    # Marking the second must have cleared the first.
    refreshed = (await client.get(f"/api/v1/runs/{first['id']}")).json()
    assert refreshed["is_baseline_for"] == []


async def test_baseline_can_be_unset(client):
    stack = await make_fake_stack(client)
    eval_set = await seeded_set(client, n=1)
    run = (
        await client.post(
            "/api/v1/runs",
            json={"set_ids": [eval_set["id"]], "executor_ids": [stack["executor"]["id"]]},
        )
    ).json()
    await wait_for_run(client, run["id"])

    await client.post(f"/api/v1/runs/{run['id']}/baseline", json={"set_ids": [eval_set["id"]]})
    unset = await client.post(
        f"/api/v1/runs/{run['id']}/baseline", json={"set_ids": [eval_set["id"]], "unset": True}
    )
    assert unset.json()["is_baseline_for"] == []


# -- settings ------------------------------------------------------------------


async def test_settings_reports_key_status_without_values(client):
    response = await client.get("/api/v1/settings")
    body = response.json()
    providers = {p["provider"]: p for p in body["providers"]}
    assert set(providers) == {"anthropic", "openai", "gemini", "openrouter"}
    assert all(p["present"] is False for p in providers.values())
    assert all(p["masked"] is None for p in providers.values())
    assert body["data_dir"]
    assert body["version"]


async def test_pricing_table_round_trips(client):
    updated = await client.patch(
        "/api/v1/settings",
        json={
            "pricing": [{"model_id": "claude-haiku", "input_per_1m": 0.8, "output_per_1m": 4.0}],
            "default_concurrency": 8,
        },
    )
    body = updated.json()
    assert body["pricing"][0]["model_id"] == "claude-haiku"
    assert body["default_concurrency"] == 8

    again = (await client.get("/api/v1/settings")).json()
    assert again["pricing"][0]["output_per_1m"] == 4.0


async def test_provider_status_endpoint_masks_a_present_key(client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-value-1234")
    response = await client.get("/api/v1/settings/providers")
    openai = next(p for p in response.json() if p["provider"] == "openai")
    assert openai["present"] is True
    assert openai["masked"] == "…1234"
    assert "sk-test-value" not in response.text


# -- SSE -----------------------------------------------------------------------


async def test_event_stream_closes_once_the_run_is_finished(client, monkeypatch):
    """A terminal run has no more deltas — the stream must end, not hang forever."""
    monkeypatch.setenv("GAUGIX_SSE_HEARTBEAT_S", "0.05")
    stack = await make_fake_stack(client)
    eval_set = await seeded_set(client, n=1)
    run = (
        await client.post(
            "/api/v1/runs",
            json={"set_ids": [eval_set["id"]], "executor_ids": [stack["executor"]["id"]]},
        )
    ).json()
    await wait_for_run(client, run["id"])

    body = await asyncio.wait_for(
        _read_stream(client, f"/api/v1/runs/{run['id']}/events"), timeout=10
    )
    assert "event: end" in body


async def _read_stream(client, url: str) -> str:
    chunks: list[str] = []
    async with client.stream("GET", url) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        async for chunk in response.aiter_text():
            chunks.append(chunk)
            if "event: end" in "".join(chunks):
                break
    return "".join(chunks)


async def test_event_stream_delivers_live_item_events(client, monkeypatch):
    monkeypatch.setenv("GAUGIX_SSE_HEARTBEAT_S", "0.05")
    stack = await make_fake_stack(client, "streamy", {"latency_ms": 40})
    eval_set = await seeded_set(client, n=3)
    run = (
        await client.post(
            "/api/v1/runs",
            json={
                "set_ids": [eval_set["id"]],
                "executor_ids": [stack["executor"]["id"]],
                "concurrency": 1,
            },
        )
    ).json()

    body = await asyncio.wait_for(
        _read_stream(client, f"/api/v1/runs/{run['id']}/events"), timeout=15
    )
    assert "event: item_status" in body
    assert "event: run_status" in body
    assert '"seq"' in body, "every event carries a monotonic seq"


async def test_event_stream_for_an_unknown_run_is_404(client):
    response = await client.get("/api/v1/runs/999/events")
    assert response.status_code == 404


# -- error taxonomy and single-item retry (PRD F3.6, F3.8) ---------------------


FAILS_ONCE = {"mode": "echo", "fail_if_contains": "boom", "error_retryable": False}


async def test_error_kinds_are_listed_with_counts(client):
    """The chips are built from the run, not the enum — no dead filters."""
    eval_set = await make_set(client, name="Broken")
    await make_case(
        client,
        title="boom one",
        input=[{"role": "user", "content": "boom"}],
        set_id=eval_set["id"],
    )
    await make_case(
        client,
        title="fine",
        input=[{"role": "user", "content": "all good"}],
        set_id=eval_set["id"],
    )
    stack = await make_fake_stack(client, "flaky", FAILS_ONCE)

    created = await client.post(
        "/api/v1/runs",
        json={"set_ids": [eval_set["id"]], "executor_ids": [stack["executor"]["id"]]},
    )
    run = await wait_for_run(client, created.json()["id"])

    kinds = (await client.get(f"/api/v1/runs/{run['id']}/error-kinds")).json()

    assert kinds, "the run errored, so at least one kind must be reported"
    assert sum(entry["count"] for entry in kinds) >= 1
    assert all(entry["kind"] for entry in kinds)


async def test_items_can_be_filtered_by_error_kind(client):
    eval_set = await make_set(client, name="Broken")
    await make_case(
        client,
        title="boom one",
        input=[{"role": "user", "content": "boom"}],
        set_id=eval_set["id"],
    )
    await make_case(
        client,
        title="fine",
        input=[{"role": "user", "content": "all good"}],
        set_id=eval_set["id"],
    )
    stack = await make_fake_stack(client, "flaky", FAILS_ONCE)

    created = await client.post(
        "/api/v1/runs",
        json={"set_ids": [eval_set["id"]], "executor_ids": [stack["executor"]["id"]]},
    )
    run = await wait_for_run(client, created.json()["id"])
    kinds = (await client.get(f"/api/v1/runs/{run['id']}/error-kinds")).json()

    filtered = (
        await client.get(f"/api/v1/runs/{run['id']}/items", params={"error_kind": kinds[0]["kind"]})
    ).json()

    assert len(filtered) == kinds[0]["count"]
    assert all(item["status"] == "error" for item in filtered)


async def test_an_unknown_error_kind_filters_to_nothing_rather_than_everything(client):
    eval_set = await make_set(client, name="Broken")
    await make_case(
        client,
        title="boom one",
        input=[{"role": "user", "content": "boom"}],
        set_id=eval_set["id"],
    )
    stack = await make_fake_stack(client, "flaky", FAILS_ONCE)
    created = await client.post(
        "/api/v1/runs",
        json={"set_ids": [eval_set["id"]], "executor_ids": [stack["executor"]["id"]]},
    )
    run = await wait_for_run(client, created.json()["id"])

    filtered = (
        await client.get(
            f"/api/v1/runs/{run['id']}/items", params={"error_kind": "not_a_real_kind"}
        )
    ).json()

    assert filtered == []


async def test_retrying_one_item_leaves_the_rest_of_the_lane_alone(client):
    """The narrow sibling of rerun-from: one bad call, one re-run."""
    eval_set = await make_set(client, name="Three")
    for i in range(3):
        await make_case(client, title=f"Case {i}", set_id=eval_set["id"])
    stack = await make_fake_stack(client, "ok")

    created = await client.post(
        "/api/v1/runs",
        json={"set_ids": [eval_set["id"]], "executor_ids": [stack["executor"]["id"]]},
    )
    run = await wait_for_run(client, created.json()["id"])
    items = (await client.get(f"/api/v1/runs/{run['id']}/items")).json()
    target = items[0]

    response = await client.post(f"/api/v1/runs/{run['id']}/items/{target['id']}/retry")
    assert response.status_code == 200, response.text
    assert response.json()["affected"] == 1
    await wait_for_run(client, run["id"])

    detail = (await client.get(f"/api/v1/items/{target['id']}")).json()
    # The first attempt is kept as superseded history, and a fresh one ran.
    assert len(detail["attempts"]) == 2
    assert sum(1 for a in detail["attempts"] if a["superseded"]) == 1

    # Every other item ran exactly once — the retry did not touch them.
    for other in items[1:]:
        other_detail = (await client.get(f"/api/v1/items/{other['id']}")).json()
        assert len(other_detail["attempts"]) == 1


async def test_retrying_an_item_from_another_run_is_a_404(client):
    eval_set = await make_set(client, name="One")
    await make_case(client, title="Case", set_id=eval_set["id"])
    stack = await make_fake_stack(client, "ok")
    created = await client.post(
        "/api/v1/runs",
        json={"set_ids": [eval_set["id"]], "executor_ids": [stack["executor"]["id"]]},
    )
    run = await wait_for_run(client, created.json()["id"])

    response = await client.post(f"/api/v1/runs/{run['id']}/items/99999/retry")
    assert response.status_code == 404


async def test_a_finished_run_offers_no_resume(client):
    """A completed run's *status* permits a resume; it has nothing to schedule.

    The button used to appear on every finished run and its only outcome was a
    "Nothing to resume" toast.
    """
    stack = await make_fake_stack(client, "strict", {"mode": "echo"})
    eval_set = await make_set(client, name="Resumable")
    await client.post(
        "/api/v1/cases",
        json={
            "title": "one",
            "input": [{"role": "user", "content": "hi"}],
            "set_id": eval_set["id"],
        },
    )
    created = await client.post(
        "/api/v1/runs",
        json={"set_ids": [eval_set["id"]], "executor_ids": [stack["executor"]["id"]]},
    )
    run = await wait_for_run(client, created.json()["id"])

    assert run["status"] == "completed"
    assert run["resumable_items"] == 0
    assert run["is_resumable"] is False

    # And the list view agrees, so the dashboard hides it too.
    listed = next(r for r in (await client.get("/api/v1/runs")).json() if r["id"] == run["id"])
    assert listed["is_resumable"] is False


# -- partial runs --------------------------------------------------------------


async def test_a_run_can_cover_part_of_a_set(client):
    """Rerunning nine cases should not mean rerunning four hundred."""
    eval_set = await make_set(client, name="Partial")
    cases = [await make_case(client, title=f"Case {i}", set_id=eval_set["id"]) for i in range(4)]
    stack = await make_fake_stack(client)

    created = await client.post(
        "/api/v1/runs",
        json={
            "set_ids": [eval_set["id"]],
            "executor_ids": [stack["executor"]["id"]],
            "case_ids": [cases[1]["id"], cases[3]["id"]],
            "start": False,
        },
    )

    assert created.status_code == 201, created.text
    run = created.json()
    assert run["totals"]["items"] == 2
    assert run["config"]["case_ids"] == sorted([cases[1]["id"], cases[3]["id"]])
    assert "(2 cases)" in run["name"], "the name must not imply the whole set"

    items = (await client.get(f"/api/v1/runs/{run['id']}/items")).json()
    assert {i["title"] for i in items} == {"Case 1", "Case 3"}


async def test_rerunning_a_partial_run_covers_the_same_cases(client):
    eval_set = await make_set(client, name="Partial")
    cases = [await make_case(client, title=f"Case {i}", set_id=eval_set["id"]) for i in range(3)]
    stack = await make_fake_stack(client)
    created = await client.post(
        "/api/v1/runs",
        json={
            "set_ids": [eval_set["id"]],
            "executor_ids": [stack["executor"]["id"]],
            "case_ids": [cases[0]["id"]],
        },
    )
    await wait_for_run(client, created.json()["id"])

    rerun = await client.post(f"/api/v1/runs/{created.json()['id']}/rerun")

    assert rerun.status_code == 201, rerun.text
    assert rerun.json()["totals"]["items"] == 1


async def test_a_preview_reports_the_subset_against_the_whole_set(client):
    eval_set = await make_set(client, name="Preview")
    cases = [await make_case(client, title=f"Case {i}", set_id=eval_set["id"]) for i in range(5)]
    stack = await make_fake_stack(client)

    response = await client.post(
        "/api/v1/runs/preview",
        json={
            "set_ids": [eval_set["id"]],
            "executor_ids": [stack["executor"]["id"]],
            "case_ids": [c["id"] for c in cases[:2]],
        },
    )

    body = response.json()
    assert body["case_count"] == 2
    assert body["available_case_count"] == 5
    assert body["sets"][0]["available_case_count"] == 5


# -- reading through a run -----------------------------------------------------


async def test_an_item_knows_its_neighbours_in_its_lane(client):
    """Reading a run means reading its failures in order, not via the board."""
    eval_set = await seeded_set(client, n=3)
    stack = await make_fake_stack(client)
    created = await client.post(
        "/api/v1/runs",
        json={"set_ids": [eval_set["id"]], "executor_ids": [stack["executor"]["id"]]},
    )
    run = await wait_for_run(client, created.json()["id"])
    items = (await client.get(f"/api/v1/runs/{run['id']}/items")).json()

    first = (await client.get(f"/api/v1/items/{items[0]['id']}")).json()
    middle = (await client.get(f"/api/v1/items/{items[1]['id']}")).json()
    last = (await client.get(f"/api/v1/items/{items[2]['id']}")).json()

    assert first["prev_item_id"] is None
    assert first["next_item_id"] == items[1]["id"]
    assert middle["prev_item_id"] == items[0]["id"]
    assert middle["next_item_id"] == items[2]["id"]
    assert last["next_item_id"] is None
    assert (middle["lane_position"], middle["lane_total"]) == (2, 3)
    assert first["run_name"] == run["name"]


async def test_neighbours_stay_inside_one_executor_lane(client):
    """Stepping off the end of one model's lane into another's would misread."""
    eval_set = await seeded_set(client, n=2)
    first = await make_fake_stack(client, "one")
    second = await make_fake_stack(client, "two")
    created = await client.post(
        "/api/v1/runs",
        json={
            "set_ids": [eval_set["id"]],
            "executor_ids": [first["executor"]["id"], second["executor"]["id"]],
        },
    )
    run = await wait_for_run(client, created.json()["id"])
    items = (await client.get(f"/api/v1/runs/{run['id']}/items")).json()

    lane = [i for i in items if i["executor_key"] == items[0]["executor_key"]]
    detail = (await client.get(f"/api/v1/items/{lane[-1]['id']}")).json()

    assert detail["lane_total"] == 2
    assert detail["next_item_id"] is None
