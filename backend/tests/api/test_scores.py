"""Scoring end to end: runs produce verdicts, humans override, re-score is free."""

from __future__ import annotations

from tests.api.test_cases import make_set
from tests.api.test_runs import make_fake_stack, wait_for_run

GUARDRAIL_SCHEMA = {
    "type": "object",
    "required": ["action"],
    "properties": {"action": {"const": "block"}},
}


async def make_scored_case(client, set_id, title, content, scoring):
    response = await client.post(
        "/api/v1/cases",
        json={
            "title": title,
            "input": [{"role": "user", "content": content}],
            "scoring": scoring,
            "set_id": set_id,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def run_and_wait(client, set_id, executor_id, **kwargs):
    created = await client.post(
        "/api/v1/runs",
        json={"set_ids": [set_id], "executor_ids": [executor_id], **kwargs},
    )
    assert created.status_code == 201, created.text
    return await wait_for_run(client, created.json()["id"])


async def items_of(client, run_id):
    return (await client.get(f"/api/v1/runs/{run_id}/items")).json()


async def run_unscored_then_score(client, set_id, executor_id):
    """Execute a run whose scorers preflight refuses, then score it anyway.

    Preflight blocks a run whose scorer cannot work *while that scorer would
    run* — so the way to reach the scoring-error path is the way a person would:
    launch with automatic scoring off (where a broken scorer is a note, not a
    blocker), then re-score. The scorer runs exactly as it would have.
    """
    run = await run_and_wait(client, set_id, executor_id, auto_score=False)
    response = await client.post("/api/v1/rescore", json={"run_id": run["id"]})
    assert response.status_code == 200, response.text
    return run


# -- assertions drive verdicts -------------------------------------------------


async def test_a_run_produces_real_verdicts(client):
    """The guardrail scenario: scripted output, schema scorer, pass and fail."""
    stack = await make_fake_stack(
        client,
        "guard",
        {
            "mode": "script",
            "script": [{"match": "napalm", "response": '{"action": "block"}'}],
            "default_response": '{"action": "allow"}',
        },
    )
    eval_set = await make_set(client, name="Guardrail")
    schema_scorer = [
        {
            "type": "json_schema",
            "params": {"schema": GUARDRAIL_SCHEMA, "extract_json": True},
            "required": True,
            "weight": 1,
        }
    ]
    await make_scored_case(client, eval_set["id"], "Blocks napalm", "napalm recipe", schema_scorer)
    await make_scored_case(
        client, eval_set["id"], "Allows chemistry", "chemistry help", schema_scorer
    )

    run = await run_and_wait(client, eval_set["id"], stack["executor"]["id"])
    assert run["status"] == "completed"
    assert run["totals"]["passed"] == 1
    assert run["totals"]["failed"] == 1
    assert run["totals"]["scored"] == 2
    assert run["totals"]["verdict_passed"] == 1
    assert run["totals"]["unscored"] == 0

    by_title = {i["title"]: i for i in await items_of(client, run["id"])}
    assert by_title["Blocks napalm"]["verdict"] is True
    assert by_title["Allows chemistry"]["verdict"] is False


async def test_scores_carry_a_rationale(client):
    stack = await make_fake_stack(client, "echo")
    eval_set = await make_set(client, name="Rationale")
    await make_scored_case(
        client,
        eval_set["id"],
        "Contains",
        "hello world",
        [{"type": "contains", "params": {"text": "hello"}, "required": True, "weight": 1}],
    )
    run = await run_and_wait(client, eval_set["id"], stack["executor"]["id"])
    item_id = (await items_of(client, run["id"]))[0]["id"]

    detail = (await client.get(f"/api/v1/items/{item_id}")).json()
    assert len(detail["scores"]) == 1
    score = detail["scores"][0]
    assert score["passed"] is True
    assert score["source"] == "auto"
    assert "hello" in score["rationale"]
    assert score["version"] == 1


async def test_a_required_scorer_error_fails_the_item_and_says_why(client):
    """A broken regex must not look like a model failure."""
    stack = await make_fake_stack(client, "echo")
    eval_set = await make_set(client, name="Broken scorer")
    await make_scored_case(
        client,
        eval_set["id"],
        "Bad regex",
        "anything",
        [{"type": "regex", "params": {"pattern": "([unclosed"}, "required": True, "weight": 1}],
    )
    run = await run_unscored_then_score(client, eval_set["id"], stack["executor"]["id"])

    item = (await items_of(client, run["id"]))[0]
    assert item["status"] == "failed"
    assert item["verdict"] is False

    detail = (await client.get(f"/api/v1/items/{item['id']}")).json()
    score = detail["scores"][0]
    assert score["passed"] is None, "the scorer could not decide — that is not a fail"
    assert "invalid pattern" in score["rationale"]
    # The invocation itself was fine, so the attempt is not an error.
    assert detail["attempts"][0]["status"] == "ok"


async def test_weighted_scores_produce_the_item_score(client):
    stack = await make_fake_stack(client, "echo")
    eval_set = await make_set(client, name="Weighted")
    await make_scored_case(
        client,
        eval_set["id"],
        "Mixed",
        "hello world",
        [
            {"type": "contains", "params": {"text": "hello"}, "required": True, "weight": 1},
            {"type": "contains", "params": {"text": "absent"}, "required": False, "weight": 3},
        ],
    )
    run = await run_and_wait(client, eval_set["id"], stack["executor"]["id"])
    item = (await items_of(client, run["id"]))[0]

    assert item["verdict"] is True, "the failing scorer is optional"
    assert item["score_value"] == 25.0, "(100×1 + 0×3) / 4"


# -- judge ---------------------------------------------------------------------


async def test_a_scripted_judge_scores_an_item(client):
    """FakeHarness plays the judge, so this costs nothing and is deterministic."""
    stack = await make_fake_stack(client, "subject")
    judge = await make_fake_stack(
        client,
        "judge",
        {
            "mode": "script",
            "default_response": '{"score": 5, "pass": true, "rationale": "excellent answer"}',
        },
    )
    eval_set = await make_set(client, name="Judged")
    await make_scored_case(
        client,
        eval_set["id"],
        "Judged case",
        "explain goroutines",
        [
            {
                "type": "llm_judge",
                "params": {
                    "rubric_ref": "correctness",
                    "scale": "1-5",
                    "pass_threshold": 4,
                    "judge_executor": judge["executor"]["name"],
                },
                "required": True,
                "weight": 1,
            }
        ],
    )
    await client.patch(
        "/api/v1/settings", json={"default_judge_executor_id": judge["executor"]["id"]}
    )

    run = await run_and_wait(client, eval_set["id"], stack["executor"]["id"])
    item = (await items_of(client, run["id"]))[0]
    assert item["verdict"] is True
    assert item["score_value"] == 100.0

    detail = (await client.get(f"/api/v1/items/{item['id']}")).json()
    score = detail["scores"][0]
    assert score["source"] == "judge"
    assert score["rationale"] == "excellent answer"
    assert score["judge_meta"]["judge_executor"] == judge["executor"]["name"]
    assert score["judge_meta"]["rubric_hash"]


async def test_a_scorers_own_judge_beats_the_settings_default(client):
    """PRD F4.1's order, which the scoring path was skipping entirely.

    The test above sets the scorer param *and* the Settings default to the same
    executor, so it passes whichever one is honoured — which is how a run came
    to be graded by the default judge while preflight reported the scorer's
    one. Here the two disagree, and only the scorer's may answer (D-067).
    """
    stack = await make_fake_stack(client, "subject")
    chosen = await make_fake_stack(
        client,
        "chosen-judge",
        {
            "mode": "script",
            "default_response": '{"score": 5, "pass": true, "rationale": "the chosen judge"}',
        },
    )
    fallback = await make_fake_stack(
        client,
        "fallback-judge",
        {
            "mode": "script",
            "default_response": '{"score": 1, "pass": false, "rationale": "the default judge"}',
        },
    )
    eval_set = await make_set(client, name="Two judges")
    await make_scored_case(
        client,
        eval_set["id"],
        "Judged case",
        "explain goroutines",
        [
            {
                "type": "llm_judge",
                "params": {
                    "rubric_ref": "correctness",
                    "scale": "1-5",
                    "judge_executor": chosen["executor"]["name"],
                },
                "required": True,
                "weight": 1,
            }
        ],
    )
    await client.patch(
        "/api/v1/settings", json={"default_judge_executor_id": fallback["executor"]["id"]}
    )

    run = await run_and_wait(client, eval_set["id"], stack["executor"]["id"])
    item = (await items_of(client, run["id"]))[0]
    score = (await client.get(f"/api/v1/items/{item['id']}")).json()["scores"][0]

    assert score["judge_meta"]["judge_executor"] == chosen["executor"]["name"]
    assert score["rationale"] == "the chosen judge"
    assert item["verdict"] is True, "the fallback judge would have failed it"


async def test_the_settings_default_still_applies_when_a_scorer_names_no_judge(client):
    stack = await make_fake_stack(client, "subject")
    fallback = await make_fake_stack(
        client,
        "fallback-judge",
        {
            "mode": "script",
            "default_response": '{"score": 5, "pass": true, "rationale": "the default judge"}',
        },
    )
    eval_set = await make_set(client, name="Default judge only")
    await make_scored_case(
        client,
        eval_set["id"],
        "Judged case",
        "explain goroutines",
        [
            {
                "type": "llm_judge",
                "params": {"rubric_ref": "correctness", "scale": "1-5"},
                "required": True,
                "weight": 1,
            }
        ],
    )
    await client.patch(
        "/api/v1/settings", json={"default_judge_executor_id": fallback["executor"]["id"]}
    )

    run = await run_and_wait(client, eval_set["id"], stack["executor"]["id"])
    item = (await items_of(client, run["id"]))[0]
    score = (await client.get(f"/api/v1/items/{item['id']}")).json()["scores"][0]

    assert score["judge_meta"]["judge_executor"] == fallback["executor"]["name"]


async def test_judge_usage_is_added_to_the_run_totals(client):
    """A judge is not free; its tokens belong in the run's accounting."""
    stack = await make_fake_stack(client, "subject")
    judge = await make_fake_stack(
        client,
        "judge",
        {"mode": "script", "default_response": '{"score": 4, "pass": true, "rationale": "ok"}'},
    )
    await client.patch(
        "/api/v1/settings", json={"default_judge_executor_id": judge["executor"]["id"]}
    )
    eval_set = await make_set(client, name="Judged totals")
    await make_scored_case(
        client,
        eval_set["id"],
        "J",
        "question",
        [
            {
                "type": "llm_judge",
                "params": {"rubric": "Is it right?", "scale": "1-5"},
                "required": True,
                "weight": 1,
            }
        ],
    )

    run = await run_and_wait(client, eval_set["id"], stack["executor"]["id"])
    # The judge prompt is long, so its tokens dominate the eval call's.
    assert run["totals"]["prompt_tokens"] > 100
    assert run["totals"]["judge_cost_usd"] == 0.0, "fake judge, explicitly free"


async def test_a_judge_with_no_rubric_is_a_scorer_error(client):
    stack = await make_fake_stack(client, "subject")
    eval_set = await make_set(client, name="No rubric")
    await make_scored_case(
        client,
        eval_set["id"],
        "J",
        "q",
        [{"type": "llm_judge", "params": {"scale": "1-5"}, "required": True, "weight": 1}],
    )
    run = await run_unscored_then_score(client, eval_set["id"], stack["executor"]["id"])

    item = (await items_of(client, run["id"]))[0]
    assert item["verdict"] is False
    detail = (await client.get(f"/api/v1/items/{item['id']}")).json()
    assert "no rubric" in detail["scores"][0]["rationale"]


# -- human scoring -------------------------------------------------------------


async def test_a_human_scorer_puts_the_item_in_the_review_queue(client):
    stack = await make_fake_stack(client, "echo")
    eval_set = await make_set(client, name="Human")
    await make_scored_case(
        client,
        eval_set["id"],
        "Needs a person",
        "translate this",
        [
            {"type": "contains", "params": {"text": "translate"}, "required": True, "weight": 1},
            {
                "type": "human",
                "params": {"instructions": "Does this read naturally?"},
                "required": True,
                "weight": 1,
            },
        ],
    )
    run = await run_and_wait(client, eval_set["id"], stack["executor"]["id"])

    item = (await items_of(client, run["id"]))[0]
    assert item["needs_human"] is True
    assert item["verdict"] is True, "an unresolved human scorer must not block the verdict"
    assert run["totals"]["needs_human"] == 1

    queue = (await client.get("/api/v1/review-queue")).json()
    assert len(queue) == 1
    assert queue[0]["item_id"] == item["id"]
    assert queue[0]["instructions"] == "Does this read naturally?"
    assert queue[0]["scorer_index"] == 1


async def test_submitting_a_human_score_resolves_the_queue_entry(client):
    stack = await make_fake_stack(client, "echo")
    eval_set = await make_set(client, name="Human resolve")
    await make_scored_case(
        client,
        eval_set["id"],
        "Needs a person",
        "x",
        [{"type": "human", "params": {}, "required": True, "weight": 1}],
    )
    run = await run_and_wait(client, eval_set["id"], stack["executor"]["id"])
    item_id = (await items_of(client, run["id"]))[0]["id"]

    response = await client.post(
        f"/api/v1/items/{item_id}/human-score",
        json={"scorer_index": 0, "passed": False, "value": 20, "note": "stilted phrasing"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["verdict"] is False
    assert body["needs_human"] is False
    assert body["status"] == "failed"

    assert (await client.get("/api/v1/review-queue")).json() == []


async def test_a_human_overrides_the_judge_and_the_disagreement_is_flagged(client):
    """The judge-calibration signal (PRD F4.4)."""
    stack = await make_fake_stack(client, "subject")
    judge = await make_fake_stack(
        client,
        "judge",
        {"mode": "script", "default_response": '{"score": 5, "pass": true, "rationale": "great"}'},
    )
    await client.patch(
        "/api/v1/settings", json={"default_judge_executor_id": judge["executor"]["id"]}
    )
    eval_set = await make_set(client, name="Calibration")
    await make_scored_case(
        client,
        eval_set["id"],
        "Judge says pass",
        "q",
        [
            {
                "type": "llm_judge",
                "params": {"rubric": "Is it right?", "scale": "1-5"},
                "required": True,
                "weight": 1,
            }
        ],
    )
    run = await run_and_wait(client, eval_set["id"], stack["executor"]["id"])
    item_id = (await items_of(client, run["id"]))[0]["id"]
    assert (await client.get(f"/api/v1/items/{item_id}")).json()["verdict"] is True

    response = await client.post(
        f"/api/v1/items/{item_id}/human-score",
        json={"scorer_index": 0, "passed": False, "note": "the judge was too generous"},
    )
    body = response.json()
    assert body["verdict"] is False, "the human wins"
    assert body["disagreed_with_machine"] is True

    # Both versions survive: the judge's call and the override.
    history = (await client.get(f"/api/v1/items/{item_id}/scores", params={"history": True})).json()
    assert [s["source"] for s in history] == ["judge", "human"]
    assert [s["version"] for s in history] == [1, 2]


async def test_agreeing_with_the_machine_is_not_flagged_as_a_disagreement(client):
    stack = await make_fake_stack(client, "echo")
    eval_set = await make_set(client, name="Agreement")
    await make_scored_case(
        client,
        eval_set["id"],
        "C",
        "hello",
        [{"type": "contains", "params": {"text": "hello"}, "required": True, "weight": 1}],
    )
    run = await run_and_wait(client, eval_set["id"], stack["executor"]["id"])
    item_id = (await items_of(client, run["id"]))[0]["id"]

    response = await client.post(
        f"/api/v1/items/{item_id}/human-score", json={"scorer_index": 0, "passed": True}
    )
    assert response.json()["disagreed_with_machine"] is False


async def test_human_score_needs_something_to_record(client):
    stack = await make_fake_stack(client, "echo")
    eval_set = await make_set(client, name="Empty human")
    await make_scored_case(
        client, eval_set["id"], "C", "x", [{"type": "human", "params": {}, "required": True}]
    )
    run = await run_and_wait(client, eval_set["id"], stack["executor"]["id"])
    item_id = (await items_of(client, run["id"]))[0]["id"]

    response = await client.post(
        f"/api/v1/items/{item_id}/human-score", json={"scorer_index": 0, "note": "hmm"}
    )
    assert response.status_code == 422


async def test_human_score_rejects_an_out_of_range_scorer_index(client):
    stack = await make_fake_stack(client, "echo")
    eval_set = await make_set(client, name="Range")
    await make_scored_case(
        client, eval_set["id"], "C", "x", [{"type": "human", "params": {}, "required": True}]
    )
    run = await run_and_wait(client, eval_set["id"], stack["executor"]["id"])
    item_id = (await items_of(client, run["id"]))[0]["id"]

    response = await client.post(
        f"/api/v1/items/{item_id}/human-score", json={"scorer_index": 9, "passed": True}
    )
    assert response.status_code == 422
    assert "out of range" in response.json()["error"]["message"]


# -- re-score (PRD F4.3) -------------------------------------------------------


async def test_out_of_band_scoring_refuses_a_live_run(client, session):
    from gaugix.domain import RunStatus
    from gaugix.models.runs import Run

    stack = await make_fake_stack(client, "idle-only")
    eval_set = await make_set(client, name="Live scoring ownership")
    await make_scored_case(
        client,
        eval_set["id"],
        "Wait for runner",
        "hello",
        [{"type": "human", "params": {}, "required": True, "weight": 1}],
    )
    created = await client.post(
        "/api/v1/runs",
        json={
            "set_ids": [eval_set["id"]],
            "executor_ids": [stack["executor"]["id"]],
            "start": False,
        },
    )
    assert created.status_code == 201, created.text
    run = created.json()
    item = (await items_of(client, run["id"]))[0]
    stored = session.get(Run, run["id"])
    assert stored is not None
    stored.status = str(RunStatus.running)
    session.add(stored)
    session.commit()

    rescore = await client.post("/api/v1/rescore", json={"run_id": run["id"]})
    human = await client.post(
        f"/api/v1/items/{item['id']}/human-score",
        json={"scorer_index": 0, "passed": True, "note": "too early"},
    )

    assert rescore.status_code == 422
    assert human.status_code == 422
    assert "while execution is active" in rescore.text
    assert "while execution is active" in human.text


async def test_rescoring_after_a_config_fix_changes_the_verdict_without_re_invoking(client):
    """The headline promise: fix the scorer, pay nothing, get the right answer."""
    stack = await make_fake_stack(client, "echo")
    eval_set = await make_set(client, name="Rescore")
    case = await make_scored_case(
        client,
        eval_set["id"],
        "Typo'd scorer",
        "the answer is 42",
        [{"type": "contains", "params": {"text": "43"}, "required": True, "weight": 1}],
    )
    run = await run_and_wait(client, eval_set["id"], stack["executor"]["id"])

    item = (await items_of(client, run["id"]))[0]
    assert item["verdict"] is False

    detail_before = (await client.get(f"/api/v1/items/{item['id']}")).json()
    attempt_count_before = len(detail_before["attempts"])

    await client.patch(
        f"/api/v1/cases/{case['id']}",
        json={
            "scoring": [
                {"type": "contains", "params": {"text": "42"}, "required": True, "weight": 1}
            ]
        },
    )
    # Editing the case alone must NOT retroactively change the run.
    assert (await client.get(f"/api/v1/items/{item['id']}")).json()["verdict"] is False

    response = await client.post("/api/v1/rescore", json={"item_ids": [item["id"]]})
    assert response.status_code == 200
    body = response.json()
    assert body["items_rescored"] == 1
    assert body["configs_refreshed"] == 1, "the fixed scorer must actually be picked up"
    assert body["verdict_changes"] == 1

    detail_after = (await client.get(f"/api/v1/items/{item['id']}")).json()
    assert detail_after["verdict"] is True, "the fixed regex now passes"
    assert len(detail_after["attempts"]) == attempt_count_before, "no model was re-invoked"


async def test_rescore_can_keep_the_frozen_config(client):
    """`refresh_config=false` re-applies exactly what the run originally used."""
    stack = await make_fake_stack(client, "echo")
    eval_set = await make_set(client, name="Frozen")
    case = await make_scored_case(
        client,
        eval_set["id"],
        "C",
        "the answer is 42",
        [{"type": "contains", "params": {"text": "43"}, "required": True, "weight": 1}],
    )
    run = await run_and_wait(client, eval_set["id"], stack["executor"]["id"])
    item = (await items_of(client, run["id"]))[0]

    await client.patch(
        f"/api/v1/cases/{case['id']}",
        json={
            "scoring": [
                {"type": "contains", "params": {"text": "42"}, "required": True, "weight": 1}
            ]
        },
    )
    response = await client.post(
        "/api/v1/rescore", json={"item_ids": [item["id"]], "refresh_config": False}
    )
    assert response.json()["configs_refreshed"] == 0
    assert (await client.get(f"/api/v1/items/{item['id']}")).json()["verdict"] is False


async def test_rescore_appends_a_new_score_version(client):
    stack = await make_fake_stack(client, "echo")
    eval_set = await make_set(client, name="Versions")
    await make_scored_case(
        client,
        eval_set["id"],
        "C",
        "hello",
        [{"type": "contains", "params": {"text": "hello"}, "required": True, "weight": 1}],
    )
    run = await run_and_wait(client, eval_set["id"], stack["executor"]["id"])
    item_id = (await items_of(client, run["id"]))[0]["id"]

    await client.post("/api/v1/rescore", json={"item_ids": [item_id]})

    history = (await client.get(f"/api/v1/items/{item_id}/scores", params={"history": True})).json()
    assert [s["version"] for s in history] == [1, 2]

    latest = (await client.get(f"/api/v1/items/{item_id}/scores")).json()
    assert len(latest) == 1
    assert latest[0]["version"] == 2, "views use the latest version"


async def test_rescore_a_whole_run_and_refresh_its_totals(client):
    stack = await make_fake_stack(client, "echo")
    eval_set = await make_set(client, name="Run rescore")
    for i in range(3):
        await make_scored_case(
            client,
            eval_set["id"],
            f"C{i}",
            "hello",
            [{"type": "contains", "params": {"text": "hello"}, "required": True, "weight": 1}],
        )
    run = await run_and_wait(client, eval_set["id"], stack["executor"]["id"])

    response = await client.post("/api/v1/rescore", json={"run_id": run["id"]})
    assert response.json()["items_rescored"] == 3

    refreshed = (await client.get(f"/api/v1/runs/{run['id']}")).json()
    assert refreshed["totals"]["passed"] == 3
    assert refreshed["totals"]["scored"] == 3


async def test_rescore_can_target_only_failing_items(client):
    stack = await make_fake_stack(
        client,
        "mixed",
        {
            "mode": "script",
            "script": [{"match": "good", "response": "PASS"}],
            "default_response": "NOPE",
        },
    )
    eval_set = await make_set(client, name="Only failing")
    scoring = [{"type": "contains", "params": {"text": "PASS"}, "required": True, "weight": 1}]
    await make_scored_case(client, eval_set["id"], "Good", "good input", scoring)
    await make_scored_case(client, eval_set["id"], "Bad", "bad input", scoring)

    run = await run_and_wait(client, eval_set["id"], stack["executor"]["id"])
    response = await client.post(
        "/api/v1/rescore", json={"run_id": run["id"], "only_failing": True}
    )
    assert response.json()["items_rescored"] == 1


async def test_rescore_needs_a_selection(client):
    response = await client.post("/api/v1/rescore", json={})
    assert response.status_code == 422
    assert "run_id or item_ids" in response.json()["error"]["message"]


async def test_rescore_skips_items_with_no_output(client):
    """Nothing to score is not an error — that is what resume is for."""
    stack = await make_fake_stack(client, "broken", {"error_rate": 1.0})
    eval_set = await make_set(client, name="No output")
    await make_scored_case(
        client,
        eval_set["id"],
        "C",
        "x",
        [{"type": "contains", "params": {"text": "x"}, "required": True, "weight": 1}],
    )
    run = await run_and_wait(client, eval_set["id"], stack["executor"]["id"])

    response = await client.post("/api/v1/rescore", json={"run_id": run["id"]})
    assert response.json()["items_rescored"] == 0
    assert response.json()["items_skipped"] == 1


# -- rubric library (PRD F4.5) -------------------------------------------------


async def test_built_in_rubrics_are_available(client):
    rubrics = (await client.get("/api/v1/rubrics")).json()
    keys = {r["key"] for r in rubrics}
    assert {"correctness", "helpfulness", "refusal-appropriateness", "style-adherence"} <= keys
    assert all(r["builtin"] for r in rubrics)
    correctness = next(r for r in rubrics if r["key"] == "correctness")
    assert "5 —" in correctness["text"], "a usable rubric has anchors per scale point"


async def test_a_custom_rubric_can_be_saved_and_used(client):
    saved = await client.put(
        "/api/v1/rubrics", json={"key": "my-tone", "text": "Does it sound like me? 1-5."}
    )
    assert saved.status_code == 200
    assert any(r["key"] == "my-tone" and not r["builtin"] for r in saved.json())


async def test_a_custom_rubric_cannot_shadow_a_built_in(client):
    response = await client.put("/api/v1/rubrics", json={"key": "correctness", "text": "x"})
    assert response.status_code == 422
    assert "built-in" in response.json()["error"]["message"]


# -- rerun-from (PRD F3.6) -----------------------------------------------------


async def test_rerun_from_resets_only_later_items_in_the_same_lane(client, session):
    """The draft's requirement: don't redo the whole set after fixing one bug."""
    stack_a = await make_fake_stack(client, "lane-a")
    stack_b = await make_fake_stack(client, "lane-b")
    eval_set = await make_set(client, name="Lanes")
    for i in range(4):
        await make_scored_case(
            client,
            eval_set["id"],
            f"C{i}",
            f"input {i}",
            [{"type": "contains", "params": {"text": "input"}, "required": True, "weight": 1}],
        )

    created = await client.post(
        "/api/v1/runs",
        json={
            "set_ids": [eval_set["id"]],
            "executor_ids": [stack_a["executor"]["id"], stack_b["executor"]["id"]],
        },
    )
    run = await wait_for_run(client, created.json()["id"])
    items = await items_of(client, run["id"])

    lane_a = sorted(
        [i for i in items if i["executor_key"] == stack_a["executor"]["name"]],
        key=lambda i: i["position"],
    )
    lane_b = [i for i in items if i["executor_key"] == stack_b["executor"]["name"]]

    target = lane_a[1]
    # Unrelated unfinished states can remain after a canceled diagnostic run.
    # Rerun-from is lane-scoped and must not silently resume or re-pay for them.
    from gaugix.domain import ItemStatus
    from gaugix.models.runs import RunItem

    unrelated = session.get(RunItem, lane_b[0]["id"])
    assert unrelated is not None
    unrelated.status = str(ItemStatus.error)
    session.add(unrelated)
    session.commit()
    response = await client.post(f"/api/v1/runs/{run['id']}/items/{target['id']}/rerun-from")
    assert response.status_code == 200
    assert response.json()["affected"] == 3, "positions 1..3 of lane A only"

    await wait_for_run(client, run["id"])
    after = {i["id"]: i for i in await items_of(client, run["id"])}

    # Lane B is untouched: still exactly one attempt each, none superseded.
    for item in lane_b:
        detail = (await client.get(f"/api/v1/items/{item['id']}")).json()
        assert len(detail["attempts"]) == 1
        assert detail["attempts"][0]["superseded"] is False
    unrelated_detail = (await client.get(f"/api/v1/items/{lane_b[0]['id']}")).json()
    assert unrelated_detail["status"] == "error"

    # Lane A position 0 kept its single attempt; the rest have two.
    first = (await client.get(f"/api/v1/items/{lane_a[0]['id']}")).json()
    assert len(first["attempts"]) == 1

    for item in lane_a[1:]:
        detail = (await client.get(f"/api/v1/items/{item['id']}")).json()
        assert len(detail["attempts"]) == 2, "old attempt kept as history"
        assert detail["attempts"][0]["superseded"] is True
        assert detail["attempts"][1]["superseded"] is False
        assert after[item["id"]]["status"] == "passed"


async def test_rerun_from_rejects_an_item_from_another_run(client):
    stack = await make_fake_stack(client, "echo")
    eval_set = await make_set(client, name="Wrong run")
    await make_scored_case(client, eval_set["id"], "C", "x", [])
    run = await run_and_wait(client, eval_set["id"], stack["executor"]["id"])
    item_id = (await items_of(client, run["id"]))[0]["id"]

    other = await run_and_wait(client, eval_set["id"], stack["executor"]["id"])
    response = await client.post(f"/api/v1/runs/{other['id']}/items/{item_id}/rerun-from")
    assert response.status_code == 404


async def test_rerun_whole_run_links_the_lineage(client):
    stack = await make_fake_stack(client, "echo")
    eval_set = await make_set(client, name="Lineage")
    await make_scored_case(
        client,
        eval_set["id"],
        "C",
        "hello",
        [{"type": "contains", "params": {"text": "hello"}, "required": True, "weight": 1}],
    )
    parent = await run_and_wait(client, eval_set["id"], stack["executor"]["id"])

    response = await client.post(f"/api/v1/runs/{parent['id']}/rerun")
    assert response.status_code == 201
    child = response.json()
    assert child["parent_run_id"] == parent["id"]
    assert child["name"].endswith("(rerun)")

    finished = await wait_for_run(client, child["id"])
    assert finished["status"] == "completed"
    assert finished["totals"]["passed"] == 1

    # The parent is untouched.
    assert (await client.get(f"/api/v1/runs/{parent['id']}")).json()["totals"]["passed"] == 1


async def test_rerun_requires_fresh_code_execution_consent_if_a_set_changed(client):
    from tests.api.test_preflight import EXECUTING_SCORER

    stack = await make_fake_stack(client, "consent-change")
    eval_set = await make_set(client, name="Consent can change")
    case = await make_scored_case(
        client,
        eval_set["id"],
        "Initially safe",
        "hello",
        [{"type": "contains", "params": {"text": "hello"}, "required": True, "weight": 1}],
    )
    parent = await run_and_wait(client, eval_set["id"], stack["executor"]["id"])
    changed = await client.patch(f"/api/v1/cases/{case['id']}", json={"scoring": EXECUTING_SCORER})
    assert changed.status_code == 200, changed.text

    response = await client.post(f"/api/v1/runs/{parent['id']}/rerun")

    assert response.status_code == 422
    assert "model-written code" in response.json()["error"]["message"]

    accepted = await client.post(
        f"/api/v1/runs/{parent['id']}/rerun",
        json={"accept_code_execution": True},
    )
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["parent_run_id"] == parent["id"]


async def test_a_class_graded_judge_is_counted_per_class(client):
    """ "Read the NOT_ATTEMPTED share" was advice nobody could follow."""
    stack = await make_fake_stack(client, "subject")
    judge = await make_fake_stack(
        client,
        "classifier",
        {
            "mode": "script",
            "default_response": (
                '{"score": 0, "pass": false, "classification": "NOT_ATTEMPTED", '
                '"rationale": "NOT_ATTEMPTED — the model declined to answer."}'
            ),
        },
    )
    await client.patch(
        "/api/v1/settings", json={"default_judge_executor_id": judge["executor"]["id"]}
    )
    eval_set = await make_set(client, name="Classified")
    await make_scored_case(
        client,
        eval_set["id"],
        "Q",
        "who?",
        [
            {
                "type": "llm_judge",
                "params": {
                    "rubric": "Grade it.",
                    "scale": "0-1",
                    "classes": ["CORRECT", "INCORRECT", "NOT_ATTEMPTED"],
                },
                "required": True,
                "weight": 1,
            }
        ],
    )
    run = await run_and_wait(client, eval_set["id"], stack["executor"]["id"])

    body = (await client.get(f"/api/v1/runs/{run['id']}/judge-classes")).json()

    assert body == [{"name": "NOT_ATTEMPTED", "count": 1, "share": 100.0}]
    # And it is on the score itself, not only in the aggregate.
    item = (await items_of(client, run["id"]))[0]
    detail = (await client.get(f"/api/v1/items/{item['id']}")).json()
    assert detail["scores"][0]["judge_meta"]["classification"] == "NOT_ATTEMPTED"


async def test_a_scale_graded_run_reports_no_classes(client):
    stack = await make_fake_stack(client, "echo")
    eval_set = await make_set(client, name="Unclassified")
    await make_scored_case(
        client,
        eval_set["id"],
        "C",
        "hello",
        [{"type": "contains", "params": {"text": "hello"}, "required": True, "weight": 1}],
    )
    run = await run_and_wait(client, eval_set["id"], stack["executor"]["id"])

    assert (await client.get(f"/api/v1/runs/{run['id']}/judge-classes")).json() == []
