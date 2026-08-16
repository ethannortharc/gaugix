"""Run preflight: everything knowable before the tokens are spent (PRD F3.1).

Each test makes one thing wrong and asserts that exactly that finding appears
with the right severity — a check that never fires is worse than no check,
because the green tick is what people act on.
"""

from __future__ import annotations

from tests.api.test_cases import make_set
from tests.api.test_runs import make_fake_stack


async def make_case(client, set_id, title="A case", scoring=None, tags=None):
    response = await client.post(
        "/api/v1/cases",
        json={
            "title": title,
            "input": [{"role": "user", "content": "hi"}],
            "scoring": scoring if scoring is not None else [],
            "tags": tags if tags is not None else [],
            "set_id": set_id,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def run_preflight(client, set_ids, executor_ids, **kwargs):
    response = await client.post(
        "/api/v1/runs/preflight",
        json={"set_ids": set_ids, "executor_ids": executor_ids, **kwargs},
    )
    assert response.status_code == 200, response.text
    return response.json()


def codes(body, severity=None):
    return [f["code"] for f in body["findings"] if severity is None or f["severity"] == severity]


CONTAINS = [{"type": "contains", "params": {"text": "ok"}, "required": True, "weight": 1}]


async def test_a_healthy_run_passes_with_nothing_to_say(client):
    eval_set = await make_set(client, name="Healthy")
    await make_case(client, eval_set["id"], scoring=CONTAINS)
    stack = await make_fake_stack(client, "fake", {"mode": "echo"})

    body = await run_preflight(client, [eval_set["id"]], [stack["executor"]["id"]])

    assert body["ok"] is True
    assert codes(body, "blocker") == []
    assert body["item_count"] == 1


async def make_direct_stack(
    client, name, *, adapter=None, capture=False, provider="openai_compatible"
):
    model = await client.post(
        "/api/v1/model-profiles",
        json={
            "name": f"{name}-model",
            "provider": provider,
            "model_id": "subject",
            **({"base_url": "http://gateway.test/v1"} if provider == "openai_compatible" else {}),
        },
    )
    assert model.status_code == 201, model.text
    config: dict[str, object] = {} if adapter is None else {"output_adapter": adapter}
    if capture:
        config["capture_http_errors"] = {
            "status_codes": [403],
            "error_codes": ["guardrails_blocked"],
        }
    harness = await client.post(
        "/api/v1/harness-profiles",
        json={"name": f"{name}-harness", "kind": "direct", "config": config},
    )
    assert harness.status_code == 201, harness.text
    executor = await client.post(
        "/api/v1/executors",
        json={
            "name": name,
            "model_profile_id": model.json()["id"],
            "harness_profile_id": harness.json()["id"],
        },
    )
    assert executor.status_code == 201, executor.text
    return executor.json()


VERDICT_SCORER = [
    {
        "type": "json_schema",
        "params": {
            "extract_json": True,
            "schema": {
                "type": "object",
                "required": ["verdict"],
                "properties": {"verdict": {"enum": ["allowed", "blocked"]}},
            },
        },
        "required": True,
        "weight": 1,
    }
]


async def test_raw_direct_executor_cannot_run_a_guardrail_verdict_set(client):
    eval_set = await make_set(client, name="Guardrail contract")
    await make_case(client, eval_set["id"], scoring=VERDICT_SCORER)
    executor = await make_direct_stack(client, "raw-direct")

    body = await run_preflight(client, [eval_set["id"]], [executor["id"]])

    assert body["ok"] is False
    assert "output_contract_mismatch" in codes(body, "blocker")


async def test_adapted_direct_executor_satisfies_a_guardrail_verdict_set(client):
    eval_set = await make_set(client, name="Guardrail contract")
    await make_case(client, eval_set["id"], scoring=VERDICT_SCORER)
    executor = await make_direct_stack(client, "adapted-direct", adapter="guardrail_verdict_v1")

    body = await run_preflight(client, [eval_set["id"]], [executor["id"]])

    assert "output_contract_mismatch" not in codes(body)


BLOCKED_VERDICT_SCORER = [
    {
        "type": "json_schema",
        "params": {
            "extract_json": True,
            "schema": {
                "type": "object",
                "required": ["verdict"],
                "properties": {"verdict": {"const": "blocked"}},
            },
        },
        "required": True,
        "weight": 1,
    }
]


async def test_adapted_direct_executor_must_capture_expected_policy_refusals(client):
    eval_set = await make_set(client, name="Blocked Guardrail contract")
    await make_case(client, eval_set["id"], scoring=BLOCKED_VERDICT_SCORER)
    executor = await make_direct_stack(
        client, "adapted-without-capture", adapter="guardrail_verdict_v1"
    )

    body = await run_preflight(client, [eval_set["id"]], [executor["id"]])

    assert body["ok"] is False
    assert "guardrail_capture_mismatch" in codes(body, "blocker")


async def test_capture_policy_satisfies_an_expected_block_contract(client):
    eval_set = await make_set(client, name="Captured Guardrail contract")
    await make_case(client, eval_set["id"], scoring=BLOCKED_VERDICT_SCORER)
    executor = await make_direct_stack(
        client,
        "adapted-with-capture",
        adapter="guardrail_verdict_v1",
        capture=True,
    )

    body = await run_preflight(client, [eval_set["id"]], [executor["id"]])

    assert "guardrail_capture_mismatch" not in codes(body)


async def test_optional_generic_verdict_property_does_not_block_raw_direct(client):
    eval_set = await make_set(client, name="Optional generic verdict")
    optional_verdict = [
        {
            "type": "json_schema",
            "params": {
                "schema": {
                    "type": "object",
                    "properties": {"verdict": {"type": "string"}},
                }
            },
            "required": True,
            "weight": 1,
        }
    ]
    await make_case(client, eval_set["id"], scoring=optional_verdict)
    executor = await make_direct_stack(client, "raw-optional-verdict")

    body = await run_preflight(client, [eval_set["id"]], [executor["id"]])

    assert "output_contract_mismatch" not in codes(body)


async def test_stub_cases_cannot_be_run_with_a_real_model(client):
    eval_set = await make_set(client, name="Needs stub")
    await make_case(client, eval_set["id"], scoring=VERDICT_SCORER, tags=["needs:stub"])
    executor = await make_direct_stack(client, "real-direct", adapter="guardrail_verdict_v1")

    body = await run_preflight(client, [eval_set["id"]], [executor["id"]])

    assert body["ok"] is False
    assert "stub_requirement_mismatch" in codes(body, "blocker")


async def test_real_api_cases_cannot_be_run_with_a_fake_profile(client):
    eval_set = await make_set(client, name="Needs real API")
    await make_case(client, eval_set["id"], scoring=CONTAINS, tags=["no-stub"])
    stack = await make_fake_stack(client, "fake", {"mode": "echo"})

    body = await run_preflight(client, [eval_set["id"]], [stack["executor"]["id"]])

    assert body["ok"] is False
    assert "real_api_requirement_mismatch" in codes(body, "blocker")


async def test_an_empty_selection_is_a_blocker_rather_than_a_crash(client):
    body = await run_preflight(client, [], [])

    assert body["ok"] is False
    assert "empty_selection" in codes(body, "blocker")


async def test_a_regex_that_does_not_compile_blocks_the_run(client):
    """This would otherwise surface as a scorer error on every item, after paying."""
    eval_set = await make_set(client, name="Bad regex")
    await make_case(
        client,
        eval_set["id"],
        scoring=[
            {"type": "regex", "params": {"pattern": "([unclosed"}, "required": True, "weight": 1}
        ],
    )
    stack = await make_fake_stack(client, "fake", {"mode": "echo"})

    body = await run_preflight(client, [eval_set["id"]], [stack["executor"]["id"]])

    assert body["ok"] is False
    assert "invalid_scorer" in codes(body, "blocker")
    finding = next(f for f in body["findings"] if f["code"] == "invalid_scorer")
    assert "compile" in finding["message"]


async def test_a_judge_scorer_with_no_rubric_blocks_the_run(client):
    eval_set = await make_set(client, name="No rubric")
    await make_case(
        client,
        eval_set["id"],
        scoring=[{"type": "llm_judge", "params": {}, "required": True, "weight": 1}],
    )
    stack = await make_fake_stack(client, "fake", {"mode": "echo"})

    body = await run_preflight(client, [eval_set["id"]], [stack["executor"]["id"]])

    assert body["ok"] is False
    finding = next(f for f in body["findings"] if f["code"] == "invalid_scorer")
    assert "rubric" in finding["message"]


async def test_a_scale_with_no_numeric_range_blocks_the_run(client):
    """`1-7` scored a top mark as 7/100 and nothing anywhere said so (D-066)."""
    eval_set = await make_set(client, name="Odd scale")
    await make_case(
        client,
        eval_set["id"],
        scoring=[
            {
                "type": "llm_judge",
                "params": {"rubric": "Good?", "scale": "likert"},
                "required": True,
                "weight": 1,
            }
        ],
    )
    stack = await make_fake_stack(client, "fake", {"mode": "echo"})

    body = await run_preflight(client, [eval_set["id"]], [stack["executor"]["id"]])

    assert body["ok"] is False
    finding = next(f for f in body["findings"] if f["code"] == "invalid_scorer")
    assert "no numeric range" in finding["message"]


async def test_a_written_out_range_scale_is_accepted(client):
    """Rejecting `1-7` outright would be the wrong fix — it is a real scale."""
    eval_set = await make_set(client, name="Seven point")
    await make_case(
        client,
        eval_set["id"],
        scoring=[
            {
                "type": "llm_judge",
                "params": {"rubric": "Good?", "scale": "1-7"},
                "required": True,
                "weight": 1,
            }
        ],
    )
    stack = await make_fake_stack(client, "fake", {"mode": "echo"})

    body = await run_preflight(client, [eval_set["id"]], [stack["executor"]["id"]])

    assert not [f for f in body["findings"] if f["code"] == "invalid_scorer"]


async def test_passing_classes_outside_the_declared_classes_blocks_the_run(client):
    """Nothing could ever pass, and the run would read as a total failure."""
    eval_set = await make_set(client, name="Stray class")
    await make_case(
        client,
        eval_set["id"],
        scoring=[
            {
                "type": "llm_judge",
                "params": {
                    "rubric": "Good?",
                    "classes": ["CORRECT", "INCORRECT"],
                    "passing_classes": ["RIGHT"],
                },
                "required": True,
                "weight": 1,
            }
        ],
    )
    stack = await make_fake_stack(client, "fake", {"mode": "echo"})

    body = await run_preflight(client, [eval_set["id"]], [stack["executor"]["id"]])

    assert body["ok"] is False
    finding = next(f for f in body["findings"] if f["code"] == "invalid_scorer")
    assert "RIGHT" in finding["message"]


async def test_a_malformed_class_list_is_a_finding_not_a_preflight_crash(client):
    eval_set = await make_set(client, name="Malformed classes")
    await make_case(
        client,
        eval_set["id"],
        scoring=[
            {
                "type": "llm_judge",
                "params": {"rubric": "Good?", "classes": 123},
                "required": True,
                "weight": 1,
            }
        ],
    )
    stack = await make_fake_stack(client, "fake", {"mode": "echo"})

    body = await run_preflight(client, [eval_set["id"]], [stack["executor"]["id"]])

    assert body["ok"] is False
    finding = next(f for f in body["findings"] if f["code"] == "invalid_scorer")
    assert "list of non-empty strings" in finding["message"]


async def test_an_invalid_pass_threshold_blocks_before_spending_tokens(client):
    eval_set = await make_set(client, name="Bad threshold")
    await make_case(
        client,
        eval_set["id"],
        scoring=[
            {
                "type": "llm_judge",
                "params": {"rubric": "Good?", "scale": "1-5", "pass_threshold": "banana"},
                "required": True,
                "weight": 1,
            }
        ],
    )
    stack = await make_fake_stack(client, "fake", {"mode": "echo"})

    body = await run_preflight(client, [eval_set["id"]], [stack["executor"]["id"]])

    assert body["ok"] is False
    finding = next(f for f in body["findings"] if f["code"] == "invalid_scorer")
    assert "finite number" in finding["message"]


async def test_python_scorer_syntax_errors_are_caught_before_running(client):
    eval_set = await make_set(client, name="Bad python")
    await make_case(
        client,
        eval_set["id"],
        scoring=[
            {
                "type": "python",
                "params": {"code": "def score(case, output)\n    return {}"},
                "required": True,
                "weight": 1,
            }
        ],
    )
    stack = await make_fake_stack(client, "fake", {"mode": "echo"})

    body = await run_preflight(client, [eval_set["id"]], [stack["executor"]["id"]])

    assert body["ok"] is False
    finding = next(f for f in body["findings"] if f["code"] == "invalid_scorer")
    assert "does not parse" in finding["message"]


async def test_cases_with_no_scorers_warn_without_blocking(client):
    """They cost a model call and produce no verdict. Worth knowing, not fatal."""
    eval_set = await make_set(client, name="Unscored")
    await make_case(client, eval_set["id"], title="no scorers", scoring=[])
    stack = await make_fake_stack(client, "fake", {"mode": "echo"})

    body = await run_preflight(client, [eval_set["id"]], [stack["executor"]["id"]])

    assert body["ok"] is True, "an unscored case is a warning, not a blocker"
    finding = next(f for f in body["findings"] if f["code"] == "unscored_cases")
    assert finding["severity"] == "warning"
    assert finding["count"] == 1


async def test_a_case_inheriting_its_sets_default_scoring_is_not_reported_unscored(client):
    """Preflight validates the *resolved* config, exactly as the planner does."""
    eval_set = await make_set(client, name="Inherits", default_scoring=CONTAINS)
    await make_case(client, eval_set["id"], scoring=[])
    stack = await make_fake_stack(client, "fake", {"mode": "echo"})

    body = await run_preflight(client, [eval_set["id"]], [stack["executor"]["id"]])

    assert "unscored_cases" not in codes(body)


async def test_a_judge_that_is_also_under_test_is_flagged(client):
    """A model grading its own answer flatters itself measurably."""
    eval_set = await make_set(client, name="Self judge")
    stack = await make_fake_stack(client, "grader", {"mode": "echo"})
    executor = stack["executor"]
    await make_case(
        client,
        eval_set["id"],
        scoring=[
            {
                "type": "llm_judge",
                "params": {"rubric": "Is it good?", "judge_executor": executor["name"]},
                "required": True,
                "weight": 1,
            }
        ],
    )

    body = await run_preflight(client, [eval_set["id"]], [executor["id"]])

    finding = next(f for f in body["findings"] if f["code"] == "judge_under_test")
    assert finding["severity"] == "warning"
    assert executor["name"] in finding["message"]


async def test_an_explicit_missing_judge_blocks_instead_of_using_the_default(client):
    eval_set = await make_set(client, name="Missing judge")
    subject = await make_fake_stack(client, "subject", {"mode": "echo"})
    fallback = await make_fake_stack(client, "fallback", {"mode": "echo"})
    await client.patch(
        "/api/v1/settings",
        json={"default_judge_executor_id": fallback["executor"]["id"]},
    )
    await make_case(
        client,
        eval_set["id"],
        scoring=[
            {
                "type": "llm_judge",
                "params": {"rubric": "Good?", "judge_executor": "does-not-exist"},
                "required": True,
                "weight": 1,
            }
        ],
    )

    body = await run_preflight(client, [eval_set["id"]], [subject["executor"]["id"]])

    assert body["ok"] is False
    finding = next(f for f in body["findings"] if f["code"] == "invalid_judge_executor")
    assert finding["severity"] == "blocker"
    assert "does-not-exist" in finding["message"]


async def test_a_case_in_two_selected_sets_is_reported_as_running_twice(client):
    shared = await make_set(client, name="First")
    other = await make_set(client, name="Second")
    case = await make_case(client, shared["id"], scoring=CONTAINS)
    await client.post(f"/api/v1/sets/{other['id']}/cases", json={"case_ids": [case["id"]]})
    stack = await make_fake_stack(client, "fake", {"mode": "echo"})

    body = await run_preflight(client, [shared["id"], other["id"]], [stack["executor"]["id"]])

    finding = next(f for f in body["findings"] if f["code"] == "duplicate_cases")
    assert finding["severity"] == "note"
    assert finding["count"] == 1
    assert body["item_count"] == 2


async def test_the_cost_estimate_states_its_assumptions(client):
    """A number with no stated assumptions gets quoted as a quote."""
    eval_set = await make_set(client, name="Costed")
    await make_case(client, eval_set["id"], scoring=CONTAINS)
    stack = await make_fake_stack(client, "fake", {"mode": "echo"})

    body = await run_preflight(client, [eval_set["id"]], [stack["executor"]["id"]])

    # Fake executors cost nothing, and the assumptions are stated regardless.
    assert body["estimated_cost_usd"] == 0.0
    assert "guess, not a quote" in body["cost_assumptions"]


async def test_preflight_writes_nothing(client):
    eval_set = await make_set(client, name="Read only")
    await make_case(client, eval_set["id"], scoring=CONTAINS)
    stack = await make_fake_stack(client, "fake", {"mode": "echo"})

    await run_preflight(client, [eval_set["id"]], [stack["executor"]["id"]])

    assert (await client.get("/api/v1/runs")).json() == []


# -- partial runs --------------------------------------------------------------


#: Reads the model's answer as a string. Python, on this machine, but yours.
PYTHON_SCORER = [
    {
        "type": "python",
        "params": {"code": "def score(case, output):\n    return {'passed': 'yes' in output}\n"},
        "required": True,
        "weight": 1,
    }
]

#: Runs the model's answer as a program. The one that has to be acknowledged.
EXECUTING_SCORER = [
    {
        "type": "python",
        "params": {
            "code": (
                "def score(case, output):\n"
                "    namespace = {}\n"
                "    exec(compile(output, '<answer>', 'exec'), namespace)\n"
                "    return {'passed': True}\n"
            )
        },
        "required": True,
        "weight": 1,
    }
]


async def test_a_subset_run_says_how_much_of_the_set_it_covers(client):
    """A pass rate over nine of four hundred cases is not the set's pass rate."""
    eval_set = await make_set(client, name="Big")
    cases = [await make_case(client, eval_set["id"], f"Case {i}", CONTAINS) for i in range(4)]
    stack = await make_fake_stack(client, "fake", {"mode": "echo"})

    body = await run_preflight(
        client,
        [eval_set["id"]],
        [stack["executor"]["id"]],
        case_ids=[cases[0]["id"], cases[2]["id"]],
    )

    assert body["case_count"] == 2
    finding = next(f for f in body["findings"] if f["code"] == "partial_set")
    assert finding["severity"] == "note"
    assert "2 of 4" in finding["message"]


async def test_a_whole_set_run_is_not_reported_as_partial(client):
    eval_set = await make_set(client, name="Whole")
    await make_case(client, eval_set["id"], scoring=CONTAINS)
    stack = await make_fake_stack(client, "fake", {"mode": "echo"})

    body = await run_preflight(client, [eval_set["id"]], [stack["executor"]["id"]])

    assert "partial_set" not in codes(body)


async def test_cases_outside_the_chosen_sets_are_reported_not_silently_dropped(client):
    chosen = await make_set(client, name="Chosen")
    elsewhere = await make_set(client, name="Elsewhere")
    inside = await make_case(client, chosen["id"], scoring=CONTAINS)
    outside = await make_case(client, elsewhere["id"], scoring=CONTAINS)
    stack = await make_fake_stack(client, "fake", {"mode": "echo"})

    body = await run_preflight(
        client,
        [chosen["id"]],
        [stack["executor"]["id"]],
        case_ids=[inside["id"], outside["id"]],
    )

    finding = next(f for f in body["findings"] if f["code"] == "cases_outside_selection")
    assert finding["count"] == 1


async def test_choosing_no_matching_cases_blocks_the_run(client):
    eval_set = await make_set(client, name="Mismatch")
    await make_case(client, eval_set["id"], scoring=CONTAINS)
    stack = await make_fake_stack(client, "fake", {"mode": "echo"})

    body = await run_preflight(client, [eval_set["id"]], [stack["executor"]["id"]], case_ids=[9999])

    assert body["ok"] is False
    assert "no_cases" in codes(body, "blocker")


# -- scoring is off ------------------------------------------------------------


async def test_a_broken_scorer_is_not_a_blocker_when_nothing_will_score(client):
    """Refusing to launch over a scorer that will not run is a dead end."""
    eval_set = await make_set(client, name="Unscored run")
    await make_case(
        client,
        eval_set["id"],
        scoring=[{"type": "regex", "params": {"pattern": "([oops"}, "required": True, "weight": 1}],
    )
    stack = await make_fake_stack(client, "fake", {"mode": "echo"})

    blocked = await run_preflight(client, [eval_set["id"]], [stack["executor"]["id"]])
    allowed = await run_preflight(
        client, [eval_set["id"]], [stack["executor"]["id"]], auto_score=False
    )

    assert blocked["ok"] is False
    assert allowed["ok"] is True
    assert "scoring_disabled" in codes(allowed, "note")


# -- code execution ------------------------------------------------------------


async def test_a_scorer_that_runs_the_answer_is_flagged_before_the_run(client):
    eval_set = await make_set(client, name="Runs code")
    await make_case(client, eval_set["id"], scoring=EXECUTING_SCORER)
    stack = await make_fake_stack(client, "fake", {"mode": "echo"})

    body = await run_preflight(client, [eval_set["id"]], [stack["executor"]["id"]])

    assert body["requires_code_execution"] is True
    assert body["code_execution_sets"] == ["Runs code"]
    assert "executes_model_output" in codes(body, "warning")


async def test_a_scorer_that_only_reads_the_answer_is_a_note_not_a_gate(client):
    """Demanding an execution acknowledgement for GSM8K's scorer teaches people
    to click through the one that matters."""
    eval_set = await make_set(client, name="Reads text")
    await make_case(client, eval_set["id"], scoring=PYTHON_SCORER)
    stack = await make_fake_stack(client, "fake", {"mode": "echo"})

    body = await run_preflight(client, [eval_set["id"]], [stack["executor"]["id"]])

    assert body["requires_code_execution"] is False
    assert "local_python_scorer" in codes(body, "note")
    assert "executes_model_output" not in codes(body)


async def test_the_catalogue_declares_which_scorers_run_the_answer(client):
    """HumanEval's scorer says so itself; GSM8K's and IFEval's say they do not."""
    from gaugix.benchmarks import get
    from gaugix.engine.preflight import executes_model_output

    def scorers(slug):
        entry = get(slug)
        assert entry is not None
        return [s for case in entry.sample_cases() for s in case.scoring]

    assert all(executes_model_output(s) for s in scorers("humaneval"))
    assert not any(executes_model_output(s) for s in scorers("gsm8k"))
    assert not any(executes_model_output(s) for s in scorers("ifeval"))


async def test_creating_a_code_executing_run_needs_an_explicit_acknowledgement(client):
    eval_set = await make_set(client, name="Runs code")
    await make_case(client, eval_set["id"], scoring=EXECUTING_SCORER)
    stack = await make_fake_stack(client, "fake", {"mode": "echo"})
    body = {
        "set_ids": [eval_set["id"]],
        "executor_ids": [stack["executor"]["id"]],
        "start": False,
    }

    refused = await client.post("/api/v1/runs", json=body)
    accepted = await client.post("/api/v1/runs", json={**body, "accept_code_execution": True})

    assert refused.status_code == 422
    assert "model-written code" in refused.json()["error"]["message"]
    assert accepted.status_code == 201


# -- the API enforces what the builder shows -----------------------------------


async def test_the_run_api_refuses_a_blocked_run_not_only_the_builder(client):
    """A script posting straight to /runs must not skip the guards."""
    eval_set = await make_set(client, name="Broken")
    await make_case(
        client,
        eval_set["id"],
        scoring=[{"type": "regex", "params": {"pattern": "([oops"}, "required": True, "weight": 1}],
    )
    stack = await make_fake_stack(client, "fake", {"mode": "echo"})

    response = await client.post(
        "/api/v1/runs",
        json={
            "set_ids": [eval_set["id"]],
            "executor_ids": [stack["executor"]["id"]],
            "start": False,
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["details"]["findings"][0]["code"] == "invalid_scorer"


# -- the judge is part of the bill ---------------------------------------------


async def priced_stack(client, name, rate):
    """A non-fake executor with known pricing, so estimates are real numbers."""
    model = await client.post(
        "/api/v1/model-profiles",
        json={
            "name": f"{name}-model",
            "provider": "openai",
            "model_id": name,
            "api_key_env": "",
            "pricing": {"input_per_1m": rate, "output_per_1m": rate},
        },
    )
    assert model.status_code == 201, model.text
    harness = await client.post(
        "/api/v1/harness-profiles", json={"name": f"{name}-harness", "kind": "direct"}
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
    return executor.json()


async def test_judge_calls_are_counted_into_the_estimate(client):
    """A judged run makes two calls per item; an estimate counting one halves it."""
    eval_set = await make_set(client, name="Judged")
    for i in range(3):
        await make_case(
            client,
            eval_set["id"],
            f"Case {i}",
            [{"type": "llm_judge", "params": {"rubric": "Good?"}, "required": True, "weight": 1}],
        )
    subject = await priced_stack(client, "subject", 10.0)
    judge = await priced_stack(client, "judge", 10.0)
    await client.patch("/api/v1/settings", json={"default_judge_executor_id": judge["id"]})

    body = await run_preflight(client, [eval_set["id"]], [subject["id"]])

    assert body["judge_call_count"] == 3
    assert body["estimated_judge_cost_usd"] > 0
    assert body["estimated_cost_usd"] > body["estimated_judge_cost_usd"]
    assert "judge calls" in body["cost_assumptions"]


async def test_an_unpriced_judge_withholds_the_estimate_rather_than_understating_it(client):
    eval_set = await make_set(client, name="Judged")
    await make_case(
        client,
        eval_set["id"],
        scoring=[
            {"type": "llm_judge", "params": {"rubric": "Good?"}, "required": True, "weight": 1}
        ],
    )
    subject = await priced_stack(client, "subject", 10.0)
    unpriced = await client.post(
        "/api/v1/model-profiles",
        json={
            "name": "mystery-model",
            "provider": "openai",
            "model_id": "mystery",
            "api_key_env": "",
        },
    )
    harness = await client.post(
        "/api/v1/harness-profiles", json={"name": "mystery-harness", "kind": "direct"}
    )
    judge = await client.post(
        "/api/v1/executors",
        json={
            "model_profile_id": unpriced.json()["id"],
            "harness_profile_id": harness.json()["id"],
        },
    )
    await client.patch("/api/v1/settings", json={"default_judge_executor_id": judge.json()["id"]})

    body = await run_preflight(client, [eval_set["id"]], [subject["id"]])

    assert body["estimated_cost_usd"] is None
    assert "judge model has no known price" in body["cost_assumptions"]
