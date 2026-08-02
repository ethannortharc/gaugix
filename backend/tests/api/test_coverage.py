"""Partial runs must not be read as facts about the whole set (D-053).

Every test here is the same shape: run part of a set, then check that the
surface which aggregates runs — the trend, the baseline, the diff, the report —
either excludes it or says what it is. A partial run's pass rate is a real
number about a real population; the bug is that it looks identical to a number
about a different population.
"""

from __future__ import annotations

from tests.api.test_cases import make_case, make_set
from tests.api.test_runs import make_fake_stack, wait_for_run

CONTAINS = [{"type": "contains", "params": {"text": "e"}, "required": True, "weight": 1}]


async def set_of(client, n=4, name="Coverage"):
    """A set whose cases actually score — an unscored item never reaches a trend."""
    eval_set = await make_set(client, name=name, default_scoring=CONTAINS)
    cases = [await make_case(client, title=f"Case {i}", set_id=eval_set["id"]) for i in range(n)]
    return eval_set, cases


async def run_over(client, set_id, executor_id, case_ids=None, name=None):
    body = {"set_ids": [set_id], "executor_ids": [executor_id]}
    if case_ids is not None:
        body["case_ids"] = case_ids
    if name:
        body["name"] = name
    created = await client.post("/api/v1/runs", json=body)
    assert created.status_code == 201, created.text
    return await wait_for_run(client, created.json()["id"])


# -- the run says what it covered ----------------------------------------------


async def test_a_run_records_what_it_covered_of_each_set(client):
    eval_set, cases = await set_of(client)
    stack = await make_fake_stack(client)

    run = await run_over(client, eval_set["id"], stack["executor"]["id"], [cases[0]["id"]])

    assert run["is_partial"] is True
    assert run["partial_coverage"] == ["Coverage: 1 of 4 cases"]
    entry = run["config"]["sets"][0]
    assert (entry["selected"], entry["available"]) == (1, 4)
    assert entry["universe"], "the exact case set must be fingerprinted"


async def test_a_whole_set_run_is_not_partial(client):
    eval_set, _ = await set_of(client)
    stack = await make_fake_stack(client)

    run = await run_over(client, eval_set["id"], stack["executor"]["id"])

    assert run["is_partial"] is False
    assert run["partial_coverage"] == []


async def test_available_is_frozen_so_a_growing_set_cannot_restate_the_past(client):
    """Recomputing the denominator later would change what the run measured."""
    eval_set, _ = await set_of(client, n=2)
    stack = await make_fake_stack(client)
    run = await run_over(client, eval_set["id"], stack["executor"]["id"])

    await make_case(client, title="Added later", set_id=eval_set["id"])
    refreshed = (await client.get(f"/api/v1/runs/{run['id']}")).json()

    assert refreshed["config"]["sets"][0]["available"] == 2
    assert refreshed["is_partial"] is False, "a full run does not become partial retroactively"


# -- the trend --------------------------------------------------------------


async def test_a_partial_run_stays_off_the_set_trend(client):
    """100% over two of five cases must not sit where the set's rate belongs."""
    eval_set, cases = await set_of(client)
    stack = await make_fake_stack(client)
    await run_over(client, eval_set["id"], stack["executor"]["id"], name="full")
    await run_over(client, eval_set["id"], stack["executor"]["id"], [cases[0]["id"]], name="part")

    trends = (await client.get("/api/v1/runs/trends")).json()

    series = next(t for t in trends if t["set_id"] == eval_set["id"])
    assert [p["run_name"] for p in series["points"]] == ["full"]
    assert series["partial_runs_excluded"] == 1


async def test_partial_runs_can_be_asked_for_explicitly_and_are_labelled(client):
    eval_set, cases = await set_of(client)
    stack = await make_fake_stack(client)
    await run_over(client, eval_set["id"], stack["executor"]["id"], [cases[0]["id"]], name="part")

    trends = (await client.get("/api/v1/runs/trends?include_partial=true")).json()

    point = next(t for t in trends if t["set_id"] == eval_set["id"])["points"][0]
    assert point["partial"] is True
    assert point["coverage"] == "1 of 4 cases"


# -- the baseline -----------------------------------------------------------


async def test_a_partial_run_cannot_become_the_baseline_by_accident(client):
    eval_set, cases = await set_of(client)
    stack = await make_fake_stack(client)
    run = await run_over(client, eval_set["id"], stack["executor"]["id"], [cases[0]["id"]])

    refused = await client.post(
        f"/api/v1/runs/{run['id']}/baseline", json={"set_ids": [eval_set["id"]]}
    )

    assert refused.status_code == 422
    assert "1 of 4 cases" in refused.json()["error"]["message"]


async def test_a_partial_baseline_is_allowed_when_asked_for_twice(client):
    eval_set, cases = await set_of(client)
    stack = await make_fake_stack(client)
    run = await run_over(client, eval_set["id"], stack["executor"]["id"], [cases[0]["id"]])

    accepted = await client.post(
        f"/api/v1/runs/{run['id']}/baseline",
        json={"set_ids": [eval_set["id"]], "allow_partial": True},
    )

    assert accepted.status_code == 200
    assert accepted.json()["is_baseline_for"] == [eval_set["id"]]


async def test_a_full_run_becomes_the_baseline_without_ceremony(client):
    eval_set, _ = await set_of(client)
    stack = await make_fake_stack(client)
    run = await run_over(client, eval_set["id"], stack["executor"]["id"])

    response = await client.post(
        f"/api/v1/runs/{run['id']}/baseline", json={"set_ids": [eval_set["id"]]}
    )

    assert response.status_code == 200


# -- the diff ---------------------------------------------------------------


async def test_a_diff_states_what_each_side_covered(client):
    eval_set, cases = await set_of(client)
    stack = await make_fake_stack(client)
    full = await run_over(client, eval_set["id"], stack["executor"]["id"])
    await client.post(f"/api/v1/runs/{full['id']}/baseline", json={"set_ids": [eval_set["id"]]})
    part = await run_over(client, eval_set["id"], stack["executor"]["id"], [cases[0]["id"]])

    diff = (await client.get(f"/api/v1/compare/diff?run_id={part['id']}")).json()

    row = next(r for r in diff["case_universes"] if r["set_id"] == eval_set["id"])
    assert row["current"] == "1 of 4 cases"
    assert row["baseline"] == "all 4 cases"
    assert row["same_universe"] is False


async def test_two_identical_full_runs_share_a_universe(client):
    eval_set, _ = await set_of(client)
    stack = await make_fake_stack(client)
    first = await run_over(client, eval_set["id"], stack["executor"]["id"])
    await client.post(f"/api/v1/runs/{first['id']}/baseline", json={"set_ids": [eval_set["id"]]})
    second = await run_over(client, eval_set["id"], stack["executor"]["id"])

    diff = (await client.get(f"/api/v1/compare/diff?run_id={second['id']}")).json()

    row = next(r for r in diff["case_universes"] if r["set_id"] == eval_set["id"])
    assert row["same_universe"] is True


# -- the report -------------------------------------------------------------


async def test_the_exported_report_declares_a_partial_run(client):
    """A report is read away from the app, with none of its context."""
    eval_set, cases = await set_of(client)
    stack = await make_fake_stack(client)
    run = await run_over(client, eval_set["id"], stack["executor"]["id"], [cases[0]["id"]])

    html = (await client.get(f"/api/v1/runs/{run['id']}/report")).text

    assert "partial run" in html
    assert "Coverage: 1 of 4 cases" in html
    assert "not comparable with a full-set run" in html


async def test_a_full_report_carries_no_partial_banner(client):
    eval_set, _ = await set_of(client)
    stack = await make_fake_stack(client)
    run = await run_over(client, eval_set["id"], stack["executor"]["id"])

    html = (await client.get(f"/api/v1/runs/{run['id']}/report")).text

    assert 'class="partial-banner"' not in html
    assert "This run covered part of its sets" not in html


# -- runs from before coverage was recorded ------------------------------------


def test_a_legacy_run_with_no_case_ids_reads_as_full():
    """Partial runs did not exist then, so a run without them was whole."""
    from gaugix import coverage

    config = {"sets": [{"id": 1, "name": "Old"}]}

    assert coverage.partial_sets(config) == []
    assert coverage.is_partial(config) is False


def test_a_legacy_full_run_says_its_size_is_unknown_not_zero():
    """It rendered as "all 0 cases" on the compare page, which is not a size."""
    from gaugix import coverage

    entry = coverage.of_run({"sets": [{"id": 1, "name": "Old"}]})[1]

    assert entry.is_partial is False
    assert entry.describe() == "full set — exact size was not recorded"


def test_a_legacy_run_with_case_ids_reads_as_partial_with_an_unknown_share():
    """Restricted, demonstrably. By how much was never written down."""
    from gaugix import coverage

    config = {"sets": [{"id": 1, "name": "Old"}], "case_ids": [1, 3]}

    thin = coverage.partial_sets(config)
    assert [c.set_id for c in thin] == [1]
    assert thin[0].describe() == "part of the set — exact coverage was not recorded"


async def test_a_run_cannot_be_the_baseline_for_a_set_it_never_covered(client):
    """An unrelated id went straight into is_baseline_for, clearing the real one."""
    covered, _ = await set_of(client, name="Covered")
    elsewhere, _ = await set_of(client, name="Elsewhere")
    stack = await make_fake_stack(client)
    run = await run_over(client, covered["id"], stack["executor"]["id"])

    refused = await client.post(
        f"/api/v1/runs/{run['id']}/baseline", json={"set_ids": [elsewhere["id"]]}
    )

    assert refused.status_code == 422
    assert "did not cover" in refused.json()["error"]["message"]
    assert (await client.get(f"/api/v1/runs/{run['id']}")).json()["is_baseline_for"] == []


async def test_a_nonexistent_set_is_refused_too(client):
    eval_set, _ = await set_of(client)
    stack = await make_fake_stack(client)
    run = await run_over(client, eval_set["id"], stack["executor"]["id"])

    refused = await client.post(f"/api/v1/runs/{run['id']}/baseline", json={"set_ids": [9999]})

    assert refused.status_code == 422


async def test_a_modified_benchmark_set_taints_the_run_it_was_measured_in(client):
    """Freezing only the install record let a report claim the original."""
    install = await client.post("/api/v1/benchmarks/gsm8k/install", json={"scope": "sample"})
    set_id = install.json()["set_id"]
    await client.post(
        "/api/v1/cases",
        json={"title": "Mine", "input": [{"role": "user", "content": "hi"}], "set_id": set_id},
    )
    stack = await make_fake_stack(client)
    run = await run_over(client, set_id, stack["executor"]["id"])

    frozen = run["config"]["sets"][0]["provenance"]
    assert frozen["modified"] is True

    html = (await client.get(f"/api/v1/runs/{run['id']}/report")).text
    assert "had been changed since it was installed" in html
    assert "not comparable with published scores" in html
