"""Settings: the pricing table, the litellm pull, and the default judge."""

from __future__ import annotations


async def make_model(client, name: str, model_id: str, provider: str = "openai"):
    body: dict = {"name": name, "provider": provider, "model_id": model_id}
    if provider == "openai_compatible":
        body["base_url"] = "http://127.0.0.1:11434/v1"
    response = await client.post("/api/v1/model-profiles", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def pricing_for(settings: dict, model_id: str) -> dict | None:
    return next((row for row in settings["pricing"] if row["model_id"] == model_id), None)


async def test_a_new_model_profile_seeds_its_own_rates(client):
    """The table used to start empty, which meant you had to know the rates already."""
    await make_model(client, "mini", "gpt-4o-mini")

    settings = (await client.get("/api/v1/settings")).json()
    row = pricing_for(settings, "gpt-4o-mini")
    assert row is not None
    assert row["source"] == "litellm"
    assert row["input_per_1m"] > 0


async def test_a_model_litellm_has_never_heard_of_still_saves(client):
    """A profile must not be blocked by a missing price."""
    await make_model(client, "local", "my-local-llama", provider="openai_compatible")

    settings = (await client.get("/api/v1/settings")).json()
    assert pricing_for(settings, "my-local-llama") is None


async def test_pull_covers_every_model_in_use_and_names_the_misses(client):
    await make_model(client, "mini", "gpt-4o-mini")
    await make_model(client, "mystery", "totally-made-up-model-9000")

    result = (await client.post("/api/v1/settings/pricing/pull", json={})).json()

    assert "totally-made-up-model-9000" in result["not_found"]
    # gpt-4o-mini was already seeded when its profile was created.
    assert "gpt-4o-mini" in result["unchanged"]
    assert result["settings"]["pricing"]


async def test_a_hand_edited_row_is_never_overwritten_by_a_pull(client):
    """The whole point of the table is that the user gets the last word."""
    await make_model(client, "mini", "gpt-4o-mini")

    saved = await client.patch(
        "/api/v1/settings",
        json={
            "pricing": [
                {
                    "model_id": "gpt-4o-mini",
                    "input_per_1m": 99.0,
                    "output_per_1m": 42.0,
                    "source": "manual",
                }
            ]
        },
    )
    assert saved.status_code == 200

    result = (await client.post("/api/v1/settings/pricing/pull", json={"refresh": True})).json()

    assert "gpt-4o-mini" in result["unchanged"]
    row = pricing_for(result["settings"], "gpt-4o-mini")
    assert row == {
        "model_id": "gpt-4o-mini",
        "input_per_1m": 99.0,
        "output_per_1m": 42.0,
        "source": "manual",
    }


async def test_a_row_saved_before_the_source_field_existed_counts_as_the_users(client):
    """Back-compat: no `source` must not silently become 'litellm' and get clobbered."""
    await client.patch(
        "/api/v1/settings",
        json={"pricing": [{"model_id": "gpt-4o-mini", "input_per_1m": 7.0, "output_per_1m": 8.0}]},
    )

    result = (await client.post("/api/v1/settings/pricing/pull", json={"refresh": True})).json()

    row = pricing_for(result["settings"], "gpt-4o-mini")
    assert row is not None
    assert row["input_per_1m"] == 7.0


async def test_pull_can_target_a_single_model(client):
    await make_model(client, "local", "my-local-llama", provider="openai_compatible")

    result = (
        await client.post(
            "/api/v1/settings/pricing/pull", json={"model_ids": ["totally-made-up-model-9000"]}
        )
    ).json()

    assert result["not_found"] == ["totally-made-up-model-9000"]
    assert result["added"] == []


async def test_the_default_judge_round_trips_and_can_be_cleared(client):
    """Judge resolution falls back to self-judging only when this is unset (PRD F4.1)."""
    assert (await client.get("/api/v1/settings")).json()["default_judge_executor_id"] is None

    model = await make_model(client, "judge-model", "gpt-4o-mini")
    harness = await client.post(
        "/api/v1/harness-profiles", json={"name": "h", "kind": "direct", "config": {}}
    )
    executor = await client.post(
        "/api/v1/executors",
        json={"model_profile_id": model["id"], "harness_profile_id": harness.json()["id"]},
    )
    executor_id = executor.json()["id"]

    saved = await client.patch("/api/v1/settings", json={"default_judge_executor_id": executor_id})
    assert saved.json()["default_judge_executor_id"] == executor_id

    cleared = await client.patch("/api/v1/settings", json={"default_judge_executor_id": None})
    assert cleared.json()["default_judge_executor_id"] is None


async def test_a_fake_model_is_not_reported_as_unpriced(client):
    """FakeHarness models cost nothing by construction — flagging them is noise."""
    await client.post(
        "/api/v1/model-profiles",
        json={"name": "sim", "provider": "fake", "model_id": "sim-model"},
    )

    result = (await client.post("/api/v1/settings/pricing/pull", json={})).json()

    assert "sim-model" not in result["not_found"]


# -- model capabilities --------------------------------------------------------


async def test_a_reasoning_model_offers_reasoning_effort(client):
    response = await client.get(
        "/api/v1/model-capabilities", params={"provider": "openai", "model_id": "o3-mini"}
    )

    body = response.json()
    assert body["known"] is True
    assert body["reasoning_effort"] is True
    assert body["effort_levels"] == ["low", "medium", "high"]


async def test_a_non_reasoning_model_does_not_offer_it(client):
    """gpt-4o-mini rejects reasoning_effort outright — offering it would just error."""
    body = (
        await client.get(
            "/api/v1/model-capabilities", params={"provider": "openai", "model_id": "gpt-4o-mini"}
        )
    ).json()

    assert body["known"] is True
    assert body["reasoning_effort"] is False
    assert body["temperature"] is True


async def test_an_unknown_model_is_permissive_rather_than_locked_down(client):
    """ "We don't know" must not render as "not supported" — a local model may well."""
    body = (
        await client.get(
            "/api/v1/model-capabilities",
            params={"provider": "openai_compatible", "model_id": "my-local-llama"},
        )
    ).json()

    assert body["known"] is False
    assert body["reasoning_effort"] is True
    assert body["temperature"] is True


async def test_a_fake_model_has_no_generation_params_to_offer(client):
    body = (
        await client.get(
            "/api/v1/model-capabilities", params={"provider": "fake", "model_id": "sim"}
        )
    ).json()

    assert body["known"] is False


async def test_reasoning_effort_survives_a_round_trip_on_a_profile(client):
    """Params are spread into the completion call, so this is all it takes to use it."""
    created = await client.post(
        "/api/v1/model-profiles",
        json={
            "name": "o3-high",
            "provider": "openai",
            "model_id": "o3-mini",
            "params": {"reasoning_effort": "high"},
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["params"] == {"reasoning_effort": "high"}


async def test_an_executor_can_override_effort_for_the_same_model(client):
    """Same model at two efforts is a comparison worth running — overrides make it one."""
    model = await make_model(client, "o3", "o3-mini")
    harness = await client.post(
        "/api/v1/harness-profiles", json={"name": "direct", "kind": "direct", "config": {}}
    )
    harness_id = harness.json()["id"]

    low = await client.post(
        "/api/v1/executors",
        json={
            "name": "o3 @ low",
            "model_profile_id": model["id"],
            "harness_profile_id": harness_id,
            "overrides": {"reasoning_effort": "low"},
        },
    )
    high = await client.post(
        "/api/v1/executors",
        json={
            "name": "o3 @ high",
            "model_profile_id": model["id"],
            "harness_profile_id": harness_id,
            "overrides": {"reasoning_effort": "high"},
        },
    )

    assert low.status_code == 201, low.text
    assert high.status_code == 201, high.text
    assert low.json()["overrides"] == {"reasoning_effort": "low"}
    assert high.json()["overrides"] == {"reasoning_effort": "high"}
