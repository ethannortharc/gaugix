"""Comparison views against hand-computed fixtures (PRD F5.2–F5.4, gate G5).

The fixture is deliberately small enough to work out on paper. Two fake
executors score the same four cases; `strict` blocks everything, `lenient`
allows everything, and the set contains two cases that *should* be blocked and
two that should not. Every expected number below is derived by hand from that,
not from a previous run of this code.
"""

from __future__ import annotations

from tests.api.test_cases import make_set
from tests.api.test_runs import make_fake_stack, wait_for_run

#: Passing means the output contains `"action": "block"`.
BLOCK_SCORER = [
    {"type": "contains", "params": {"text": '"action": "block"'}, "required": True, "weight": 1}
]
#: Passing means it does *not* — a benign request must be allowed through.
ALLOW_SCORER = [
    {"type": "not_contains", "params": {"text": '"action": "block"'}, "required": True, "weight": 1}
]

BLOCKS_EVERYTHING = {"mode": "script", "default_response": '{"action": "block"}'}
ALLOWS_EVERYTHING = {"mode": "script", "default_response": '{"action": "allow"}'}


async def make_case(client, set_id, title, scoring):
    response = await client.post(
        "/api/v1/cases",
        json={
            "title": title,
            "input": [{"role": "user", "content": title}],
            "scoring": scoring,
            "set_id": set_id,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def fixture(client):
    """Two executors × four cases. Strict passes 2/4, lenient passes 2/4 — the other 2."""
    eval_set = await make_set(client, name="Guardrails")
    await make_case(client, eval_set["id"], "jailbreak one", BLOCK_SCORER)
    await make_case(client, eval_set["id"], "jailbreak two", BLOCK_SCORER)
    await make_case(client, eval_set["id"], "benign one", ALLOW_SCORER)
    await make_case(client, eval_set["id"], "benign two", ALLOW_SCORER)

    strict = await make_fake_stack(client, "strict", BLOCKS_EVERYTHING)
    lenient = await make_fake_stack(client, "lenient", ALLOWS_EVERYTHING)
    return {
        "set": eval_set,
        "strict": strict["executor"],
        "lenient": lenient["executor"],
    }


async def run_both(client, env, **kwargs):
    created = await client.post(
        "/api/v1/runs",
        json={
            "set_ids": [env["set"]["id"]],
            "executor_ids": [env["strict"]["id"], env["lenient"]["id"]],
            **kwargs,
        },
    )
    assert created.status_code == 201, created.text
    return await wait_for_run(client, created.json()["id"])


# -- leaderboard (PRD F5.4) ----------------------------------------------------


async def test_leaderboard_counts_match_the_hand_computed_fixture(client):
    env = await fixture(client)
    run = await run_both(client, env)

    body = (await client.get("/api/v1/compare/leaderboard", params={"run_id": run["id"]})).json()

    assert body["totals"]["items"] == 8
    assert {row["executor_key"] for row in body["rows"]} == {
        env["strict"]["name"],
        env["lenient"]["name"],
    }
    for row in body["rows"]:
        # Each executor blocks (or allows) everything, so it gets the two cases
        # that wanted that answer right and the two that wanted the other wrong.
        assert row["items"] == 4, row
        assert row["scored"] == 4, row
        assert row["passed"] == 2, row
        assert row["failed"] == 2, row
        assert row["pass_rate"] == 50.0, row


async def test_leaderboard_ranks_the_better_executor_first(client):
    """Give strict a set it aces, so the ordering has something to say."""
    env = await fixture(client)
    only_jailbreaks = await make_set(client, name="Jailbreaks only")
    await make_case(client, only_jailbreaks["id"], "jailbreak three", BLOCK_SCORER)
    await make_case(client, only_jailbreaks["id"], "jailbreak four", BLOCK_SCORER)

    created = await client.post(
        "/api/v1/runs",
        json={
            "set_ids": [only_jailbreaks["id"]],
            "executor_ids": [env["strict"]["id"], env["lenient"]["id"]],
        },
    )
    run = await wait_for_run(client, created.json()["id"])

    body = (await client.get("/api/v1/compare/leaderboard", params={"run_id": run["id"]})).json()

    assert body["rows"][0]["executor_key"] == env["strict"]["name"]
    assert body["rows"][0]["pass_rate"] == 100.0
    assert body["rows"][0]["rank"] == 1
    assert body["rows"][1]["pass_rate"] == 0.0
    assert body["rows"][1]["rank"] == 2


async def test_a_fake_run_costs_nothing_and_says_so(client):
    """Fake calls are priced at zero, which is true — not an unknown dressed as zero."""
    env = await fixture(client)
    run = await run_both(client, env)

    body = (await client.get("/api/v1/compare/leaderboard", params={"run_id": run["id"]})).json()

    assert body["totals"]["cost_usd"] == 0.0
    assert body["totals"]["cost_unknown"] is False
    assert body["totals"]["prompt_tokens"] > 0


# -- matrix (PRD F5.2) ---------------------------------------------------------


async def test_matrix_is_cases_by_executors(client):
    env = await fixture(client)
    run = await run_both(client, env)

    body = (await client.get("/api/v1/compare/matrix", params={"run_id": run["id"]})).json()

    assert len(body["rows"]) == 4
    assert body["executors"] == sorted([env["strict"]["name"], env["lenient"]["name"]])

    by_title = {row["title"]: row for row in body["rows"]}
    # A case that must be blocked: strict is right, lenient is wrong.
    jailbreak = by_title["jailbreak one"]["cells"]
    assert jailbreak[env["strict"]["name"]]["verdict"] is True
    assert jailbreak[env["lenient"]["name"]]["verdict"] is False
    # A benign case: exactly the other way round.
    benign = by_title["benign one"]["cells"]
    assert benign[env["strict"]["name"]]["verdict"] is False
    assert benign[env["lenient"]["name"]]["verdict"] is True


async def test_matrix_cells_link_back_to_their_items(client):
    """Click-through is the whole point of a cell (PRD F5.2)."""
    env = await fixture(client)
    run = await run_both(client, env)

    body = (await client.get("/api/v1/compare/matrix", params={"run_id": run["id"]})).json()
    cell = body["rows"][0]["cells"][body["executors"][0]]

    item = await client.get(f"/api/v1/items/{cell['item_id']}")
    assert item.status_code == 200
    assert item.json()["run_id"] == run["id"]


# -- aggregate matrix (PRD F5.2) -----------------------------------------------


async def test_aggregate_is_sets_by_executors(client):
    env = await fixture(client)
    run = await run_both(client, env)

    body = (await client.get("/api/v1/compare/aggregate", params={"run_id": run["id"]})).json()

    assert len(body["rows"]) == 1
    row = body["rows"][0]
    assert row["set_name"] == "Guardrails"
    assert row["cells"][env["strict"]["name"]]["pass_rate"] == 50.0
    assert row["cells"][env["strict"]["name"]]["items"] == 4
    assert row["totals"]["items"] == 8


# -- regression diff (PRD F5.3) ------------------------------------------------


async def test_diff_finds_the_regression_when_an_executor_gets_stricter(client):
    """Baseline: lenient allows everything. Current: it blocks everything.

    Hand-computed: the two benign cases go pass → fail (regressions), the two
    jailbreaks go fail → pass (improvements). Nothing new, nothing removed.
    """
    eval_set = await make_set(client, name="Guardrails")
    await make_case(client, eval_set["id"], "jailbreak one", BLOCK_SCORER)
    await make_case(client, eval_set["id"], "jailbreak two", BLOCK_SCORER)
    await make_case(client, eval_set["id"], "benign one", ALLOW_SCORER)
    await make_case(client, eval_set["id"], "benign two", ALLOW_SCORER)

    before = await make_fake_stack(client, "v1", ALLOWS_EVERYTHING)
    after = await make_fake_stack(client, "v2", BLOCKS_EVERYTHING)

    baseline = await wait_for_run(
        client,
        (
            await client.post(
                "/api/v1/runs",
                json={"set_ids": [eval_set["id"]], "executor_ids": [before["executor"]["id"]]},
            )
        ).json()["id"],
    )
    current = await wait_for_run(
        client,
        (
            await client.post(
                "/api/v1/runs",
                json={"set_ids": [eval_set["id"]], "executor_ids": [after["executor"]["id"]]},
            )
        ).json()["id"],
    )

    body = (
        await client.get(
            "/api/v1/compare/diff",
            params={"run_id": current["id"], "baseline_run_id": baseline["id"]},
        )
    ).json()

    # The two runs used different executors, so nothing pairs up — and the reply
    # says so plainly instead of reporting a total wipeout.
    assert body["executors"]["only_current"] == [after["executor"]["name"]]
    assert body["executors"]["only_baseline"] == [before["executor"]["name"]]
    assert body["counts"]["new"] == 4
    assert body["counts"]["removed"] == 4
    assert body["pass_rate"]["current"] == 50.0
    assert body["pass_rate"]["baseline"] == 50.0


async def test_diff_pairs_items_when_the_executor_is_the_same(client):
    """Same executor, same cases, one case edited between runs → one regression."""
    eval_set = await make_set(client, name="Guardrails")
    keeper = await make_case(client, eval_set["id"], "jailbreak one", BLOCK_SCORER)
    await make_case(client, eval_set["id"], "jailbreak two", BLOCK_SCORER)

    stack = await make_fake_stack(client, "strict", BLOCKS_EVERYTHING)
    executor_id = stack["executor"]["id"]

    baseline = await wait_for_run(
        client,
        (
            await client.post(
                "/api/v1/runs",
                json={"set_ids": [eval_set["id"]], "executor_ids": [executor_id]},
            )
        ).json()["id"],
    )

    # Flip one case's expectation: the model has not changed, the bar has.
    patched = await client.patch(f"/api/v1/cases/{keeper['id']}", json={"scoring": ALLOW_SCORER})
    assert patched.status_code == 200, patched.text

    current = await wait_for_run(
        client,
        (
            await client.post(
                "/api/v1/runs",
                json={"set_ids": [eval_set["id"]], "executor_ids": [executor_id]},
            )
        ).json()["id"],
    )

    body = (
        await client.get(
            "/api/v1/compare/diff",
            params={"run_id": current["id"], "baseline_run_id": baseline["id"]},
        )
    ).json()

    assert body["counts"]["regressed"] == 1
    assert body["counts"]["unchanged"] == 1
    assert body["counts"]["new"] == 0
    assert body["counts"]["removed"] == 0

    regression = next(e for e in body["entries"] if e["kind"] == "regressed")
    assert regression["title"] == "jailbreak one"
    assert regression["baseline_verdict"] is True
    assert regression["current_verdict"] is False


async def test_diff_finds_the_baseline_by_itself(client):
    """ "Did this regress?" should not require looking a run id up by hand."""
    env = await fixture(client)
    baseline = await run_both(client, env)
    marked = await client.post(
        f"/api/v1/runs/{baseline['id']}/baseline", json={"set_ids": [env["set"]["id"]]}
    )
    assert marked.status_code == 200, marked.text

    current = await run_both(client, env)

    body = (await client.get("/api/v1/compare/diff", params={"run_id": current["id"]})).json()

    assert body["baseline_run_id"] == baseline["id"]
    # Identical runs of an unchanged fixture: everything holds steady.
    assert body["counts"]["regressed"] == 0
    assert body["counts"]["improved"] == 0
    assert body["counts"]["unchanged"] == 8


async def test_diff_without_a_baseline_answers_rather_than_erroring(client):
    """ "No baseline yet" is a state of the world, not a malformed request.

    Returning 4xx here made the browser log a console error on a page that was
    behaving correctly, which is exactly the kind of noise that trains people to
    ignore the console.
    """
    env = await fixture(client)
    run = await run_both(client, env)

    response = await client.get("/api/v1/compare/diff", params={"run_id": run["id"]})

    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False
    assert "baseline" in (body["reason"] or "").lower()
    assert body["entries"] == []


async def test_a_run_cannot_be_its_own_baseline(client):
    env = await fixture(client)
    run = await run_both(client, env)

    response = await client.get(
        "/api/v1/compare/diff",
        params={"run_id": run["id"], "baseline_run_id": run["id"]},
    )

    assert response.status_code == 422


# -- the honesty rules ---------------------------------------------------------


async def test_an_unscored_item_is_never_counted_as_a_failure(client):
    """A case with no scorers is 'done, unscored' — pass rate must ignore it (D-014)."""
    eval_set = await make_set(client, name="Unscored")
    await make_case(client, eval_set["id"], "no scorers here", [])
    await make_case(client, eval_set["id"], "jailbreak one", BLOCK_SCORER)
    stack = await make_fake_stack(client, "strict", BLOCKS_EVERYTHING)

    run = await wait_for_run(
        client,
        (
            await client.post(
                "/api/v1/runs",
                json={"set_ids": [eval_set["id"]], "executor_ids": [stack["executor"]["id"]]},
            )
        ).json()["id"],
    )

    body = (await client.get("/api/v1/compare/leaderboard", params={"run_id": run["id"]})).json()
    row = body["rows"][0]

    assert row["items"] == 2
    assert row["scored"] == 1
    assert row["unscored"] == 1
    # 1 of 1 scored, not 1 of 2 items.
    assert row["pass_rate"] == 100.0


async def test_an_unresolved_pair_is_reported_rather_than_bucketed(client):
    """Neither pass nor fail: an unscored side gets its own bucket, with a reason."""
    eval_set = await make_set(client, name="Mixed")
    await make_case(client, eval_set["id"], "no scorers here", [])
    stack = await make_fake_stack(client, "strict", BLOCKS_EVERYTHING)
    executor_id = stack["executor"]["id"]

    runs = []
    for _ in range(2):
        created = await client.post(
            "/api/v1/runs",
            json={"set_ids": [eval_set["id"]], "executor_ids": [executor_id]},
        )
        runs.append(await wait_for_run(client, created.json()["id"]))

    body = (
        await client.get(
            "/api/v1/compare/diff",
            params={"run_id": runs[1]["id"], "baseline_run_id": runs[0]["id"]},
        )
    ).json()

    assert body["counts"]["unresolved"] == 1
    assert body["counts"]["regressed"] == 0
    entry = next(e for e in body["entries"] if e["kind"] == "unresolved")
    assert "unscored" in (entry["note"] or "")


# -- picker options ------------------------------------------------------------


async def test_options_only_offer_runs_that_have_something_to_compare(client):
    env = await fixture(client)
    run = await run_both(client, env)

    body = (await client.get("/api/v1/compare/options")).json()

    assert [r["id"] for r in body["runs"]] == [run["id"]]
    assert body["runs"][0]["set_ids"] == [env["set"]["id"]]
    assert [s["name"] for s in body["sets"]] == ["Guardrails"]
    assert body["executors"] == sorted([env["strict"]["name"], env["lenient"]["name"]])


async def test_comparing_a_run_that_does_not_exist_is_a_404(client):
    response = await client.get("/api/v1/compare/leaderboard", params={"run_id": 9999})
    assert response.status_code == 404


async def test_comparing_nothing_is_refused(client):
    response = await client.get("/api/v1/compare/leaderboard")
    assert response.status_code == 422


# -- the boundaries a wrong number hides in (D-029, D-030, D-031) --------------


async def test_a_case_in_two_sets_produces_two_independent_diff_entries(client):
    """Set membership is part of an item's identity.

    The same case can sit in two sets, so a run covering both produces two
    genuinely different items for it. Keying the diff on (case, executor) alone
    let one overwrite the other in a dict, and a result vanished silently.
    """
    shared = await make_set(client, name="Shared")
    other = await make_set(client, name="Other")
    case = await make_case(client, shared["id"], "jailbreak one", BLOCK_SCORER)
    attached = await client.post(
        f"/api/v1/sets/{other['id']}/cases", json={"case_ids": [case["id"]]}
    )
    assert attached.status_code == 200, attached.text

    strict = (await make_fake_stack(client, "strict", BLOCKS_EVERYTHING))["executor"]
    payload = {"set_ids": [shared["id"], other["id"]], "executor_ids": [strict["id"]]}
    baseline = await wait_for_run(
        client, (await client.post("/api/v1/runs", json=payload)).json()["id"]
    )
    current = await wait_for_run(
        client, (await client.post("/api/v1/runs", json=payload)).json()["id"]
    )

    body = (
        await client.get(
            "/api/v1/compare/diff",
            params={"run_id": current["id"], "baseline_run_id": baseline["id"]},
        )
    ).json()

    # One entry per (set, case, executor) — two, not one.
    assert len(body["entries"]) == 2
    assert sorted(e["set_name"] for e in body["entries"]) == ["Other", "Shared"]
    assert body["counts"]["unchanged"] == 2
    assert body["counts"]["new"] == 0 and body["counts"]["removed"] == 0


async def test_two_sets_with_different_baselines_are_not_mixed_together(client):
    """Each set's baseline is its own; the diff covers one and names the other.

    Previously the first baseline found was applied to every set in the run, so
    one set was compared against a run that had never covered it.
    """
    guardrails = await make_set(client, name="Guardrails")
    await make_case(client, guardrails["id"], "jailbreak one", BLOCK_SCORER)
    manners = await make_set(client, name="Manners")
    await make_case(client, manners["id"], "benign one", ALLOW_SCORER)
    strict = (await make_fake_stack(client, "strict", BLOCKS_EVERYTHING))["executor"]

    async def run(set_ids):
        created = await client.post(
            "/api/v1/runs", json={"set_ids": set_ids, "executor_ids": [strict["id"]]}
        )
        return await wait_for_run(client, created.json()["id"])

    guardrails_baseline = await run([guardrails["id"]])
    manners_baseline = await run([manners["id"]])
    await client.post(
        f"/api/v1/runs/{guardrails_baseline['id']}/baseline", json={"set_ids": [guardrails["id"]]}
    )
    await client.post(
        f"/api/v1/runs/{manners_baseline['id']}/baseline", json={"set_ids": [manners["id"]]}
    )

    current = await run([guardrails["id"], manners["id"]])
    body = (await client.get("/api/v1/compare/diff", params={"run_id": current["id"]})).json()

    # Exactly one set is in scope, and it is the one that blessed this baseline.
    assert body["scoped_set_ids"] in ([guardrails["id"]], [manners["id"]])
    covered = body["scoped_set_ids"][0]
    assert body["baseline_run_id"] == (
        guardrails_baseline["id"] if covered == guardrails["id"] else manners_baseline["id"]
    )
    assert len(body["entries"]) == 1

    # The excluded set is reported, not dropped, and it says what it needs.
    excluded = next(c for c in body["coverage"] if not c["included"])
    assert excluded["baseline_run_id"] is not None
    assert "different run" in (excluded["reason"] or "")


async def test_no_overall_delta_when_the_two_runs_share_no_executor(client):
    """A pass rate that moved because the executors changed is not a regression.

    Every entry here is new or removed, so subtracting the two overall rates
    produces a number that reads as a 6-point drop and means nothing.
    """
    env = await fixture(client)

    async def run_with(executor):
        created = await client.post(
            "/api/v1/runs",
            json={"set_ids": [env["set"]["id"]], "executor_ids": [executor["id"]]},
        )
        return await wait_for_run(client, created.json()["id"])

    baseline = await run_with(env["strict"])
    current = await run_with(env["lenient"])

    body = (
        await client.get(
            "/api/v1/compare/diff",
            params={"run_id": current["id"], "baseline_run_id": baseline["id"]},
        )
    ).json()

    assert body["executors"]["both"] == []
    assert body["comparable"] is False
    assert body["paired"]["items"] == 0
    assert body["paired"]["pass_rate"]["current"] is None
    assert body["paired"]["pass_rate"]["baseline"] is None
    # The unpaired totals still exist as context, but nothing pairs up.
    assert body["counts"]["new"] == 4 and body["counts"]["removed"] == 4
    assert body["counts"]["regressed"] == 0


async def test_paired_metrics_ignore_the_executor_only_one_run_had(client):
    """With a partial overlap, the honest delta covers the shared executor only."""
    env = await fixture(client)

    baseline_created = await client.post(
        "/api/v1/runs",
        json={"set_ids": [env["set"]["id"]], "executor_ids": [env["strict"]["id"]]},
    )
    baseline = await wait_for_run(client, baseline_created.json()["id"])
    current = await run_both(client, env)

    body = (
        await client.get(
            "/api/v1/compare/diff",
            params={"run_id": current["id"], "baseline_run_id": baseline["id"]},
        )
    ).json()

    assert body["executors"]["both"] == [env["strict"]["name"]]
    assert body["comparable"] is True
    # Four shared identities: the strict executor's four cases.
    assert body["paired"]["items"] == 4
    assert body["paired"]["pass_rate"]["current"] == 50.0
    assert body["paired"]["pass_rate"]["baseline"] == 50.0
    # Unpaired, the current run also carries lenient's four cases.
    assert body["counts"]["new"] == 4


async def test_set_trends_are_computed_per_set_not_per_run(client):
    """One run, two sets, two genuinely different pass rates.

    The dashboard used to plot the run's overall rate on every set it touched,
    so a set that aced its cases and a set that failed all of them both showed
    the same 50% — and a regression in one could only ever appear in both.
    """
    jailbreaks = await make_set(client, name="Jailbreaks")
    await make_case(client, jailbreaks["id"], "jailbreak one", BLOCK_SCORER)
    await make_case(client, jailbreaks["id"], "jailbreak two", BLOCK_SCORER)
    benign = await make_set(client, name="Benign")
    await make_case(client, benign["id"], "benign one", ALLOW_SCORER)
    await make_case(client, benign["id"], "benign two", ALLOW_SCORER)

    strict = (await make_fake_stack(client, "strict", BLOCKS_EVERYTHING))["executor"]
    created = await client.post(
        "/api/v1/runs",
        json={"set_ids": [jailbreaks["id"], benign["id"]], "executor_ids": [strict["id"]]},
    )
    run = await wait_for_run(client, created.json()["id"])

    # The run as a whole: 2 of 4 passed. Neither set actually scored 50%.
    assert run["totals"]["verdict_passed"] == 2 and run["totals"]["scored"] == 4

    trends = (await client.get("/api/v1/runs/trends")).json()
    rates = {t["set_name"]: t["points"][-1]["pass_rate"] for t in trends}

    assert rates == {"Jailbreaks": 100.0, "Benign": 0.0}
    for trend in trends:
        assert [p["run_id"] for p in trend["points"]] == [run["id"]]
        assert trend["points"][-1]["scored"] == 2
