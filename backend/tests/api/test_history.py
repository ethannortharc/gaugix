"""Set- and case-centred projections over immutable run history."""

from __future__ import annotations

from gaugix.models.runs import Run, RunItem
from tests.api.test_cases import make_case, make_set
from tests.api.test_runs import make_fake_stack, wait_for_run

SCORING = [{"type": "contains", "params": {"text": "PASS"}, "required": True, "weight": 1}]


async def create_history_fixture(client):
    alpha = await make_set(client, name="Alpha set")
    beta = await make_set(client, name="Beta set")
    first = await make_case(
        client,
        title="Alpha one",
        input=[{"role": "user", "content": "good one"}],
        scoring=SCORING,
        set_id=alpha["id"],
    )
    second = await make_case(
        client,
        title="Alpha two",
        input=[{"role": "user", "content": "good two"}],
        scoring=SCORING,
        set_id=alpha["id"],
    )
    await make_case(
        client,
        title="Beta one",
        input=[{"role": "user", "content": "bad"}],
        scoring=SCORING,
        set_id=beta["id"],
    )
    harness = {
        "mode": "script",
        "script": [{"match": "good", "response": "PASS from executor"}],
        "default_response": "NO",
    }
    one = await make_fake_stack(client, "history-one", harness)
    two = await make_fake_stack(client, "history-two", harness)

    whole_response = await client.post(
        "/api/v1/runs",
        json={
            "name": "Whole benchmark",
            "set_ids": [alpha["id"], beta["id"]],
            "executor_ids": [one["executor"]["id"], two["executor"]["id"]],
        },
    )
    assert whole_response.status_code == 201, whole_response.text
    whole = await wait_for_run(client, whole_response.json()["id"])

    partial_response = await client.post(
        "/api/v1/runs",
        json={
            "name": "One-case check",
            "set_ids": [alpha["id"]],
            "case_ids": [first["id"]],
            "executor_ids": [one["executor"]["id"]],
        },
    )
    assert partial_response.status_code == 201, partial_response.text
    partial = await wait_for_run(client, partial_response.json()["id"])

    baseline = await client.post(
        f"/api/v1/runs/{whole['id']}/baseline",
        json={"set_ids": [alpha["id"]]},
    )
    assert baseline.status_code == 200, baseline.text
    return alpha, beta, first, second, one, two, whole, partial


async def test_set_history_uses_set_scoped_verdicts_and_frozen_coverage(client):
    alpha, beta, _first, _second, one, two, whole, partial = await create_history_fixture(client)

    alpha_response = await client.get(f"/api/v1/sets/{alpha['id']}/runs")
    beta_response = await client.get(f"/api/v1/sets/{beta['id']}/runs")
    assert alpha_response.headers["X-Total-Count"] == "2"
    assert beta_response.headers["X-Total-Count"] == "1"

    alpha_rows = alpha_response.json()
    assert [row["run_id"] for row in alpha_rows] == [partial["id"], whole["id"]]
    assert alpha_rows[0]["coverage"] == "1 of 2 cases"
    assert alpha_rows[0]["is_partial"] is True
    assert alpha_rows[0]["item_count"] == 1
    assert alpha_rows[0]["case_count"] == 1
    assert alpha_rows[0]["pass_rate"] == 100.0
    assert alpha_rows[1]["coverage"] == "all 2 cases"
    assert alpha_rows[1]["item_count"] == 4
    assert alpha_rows[1]["case_count"] == 2
    assert alpha_rows[1]["executor_keys"] == sorted(
        [one["executor"]["name"], two["executor"]["name"]]
    )
    assert alpha_rows[1]["is_baseline"] is True
    assert alpha_rows[1]["pass_rate"] == 100.0

    beta_row = beta_response.json()[0]
    assert beta_row["run_id"] == whole["id"]
    assert beta_row["item_count"] == 2
    assert beta_row["scored"] == 2
    assert beta_row["passed"] == 0
    assert beta_row["failed"] == 2
    assert beta_row["pass_rate"] == 0.0

    first_page = await client.get(f"/api/v1/sets/{alpha['id']}/runs", params={"limit": 1})
    assert len(first_page.json()) == 1
    assert first_page.headers["X-Total-Count"] == "2"
    second_page = await client.get(
        f"/api/v1/sets/{alpha['id']}/runs", params={"limit": 1, "offset": 1}
    )
    assert [row["run_id"] for row in second_page.json()] == [whole["id"]]
    assert (
        await client.get(f"/api/v1/sets/{alpha['id']}/runs", params={"limit": 1000})
    ).status_code == 200


async def test_case_history_is_one_row_per_run_item_and_links_to_exact_result(client):
    alpha, _beta, first, _second, one, two, whole, partial = await create_history_fixture(client)

    response = await client.get(f"/api/v1/cases/{first['id']}/run-items")
    assert response.status_code == 200
    assert response.headers["X-Total-Count"] == "3"
    rows = response.json()
    assert len({row["item_id"] for row in rows}) == 3
    assert rows[0]["run_id"] == partial["id"]
    assert {row["executor_key"] for row in rows} == {
        one["executor"]["name"],
        two["executor"]["name"],
    }
    assert sum(row["run_id"] == whole["id"] for row in rows) == 2
    assert all(row["set_id"] == alpha["id"] for row in rows)
    assert all(row["set_name"] == "Alpha set" for row in rows)
    assert all(row["verdict"] is True for row in rows)
    assert all(row["output_preview"] == "PASS from executor" for row in rows)
    assert all(row["attempt_n"] == 1 for row in rows)


async def test_empty_and_unknown_entity_history_are_distinct(client):
    eval_set = await make_set(client, name="Never run")
    case = await make_case(client, title="Never run case", set_id=eval_set["id"])

    set_response = await client.get(f"/api/v1/sets/{eval_set['id']}/runs")
    case_response = await client.get(f"/api/v1/cases/{case['id']}/run-items")
    assert set_response.json() == []
    assert set_response.headers["X-Total-Count"] == "0"
    assert case_response.json() == []
    assert case_response.headers["X-Total-Count"] == "0"
    assert (await client.get("/api/v1/sets/999/runs")).status_code == 404
    assert (await client.get("/api/v1/cases/999/run-items")).status_code == 404


async def test_legacy_history_names_unknown_full_and_partial_coverage(client, session):
    eval_set = await make_set(client, name="Legacy set")
    case = await make_case(client, title="Legacy case", set_id=eval_set["id"])

    full = Run(name="Legacy full", status="completed")
    full.config = {}
    session.add(full)
    session.flush()
    assert full.id is not None
    session.add(
        RunItem(
            run_id=full.id,
            set_id=eval_set["id"],
            set_name=eval_set["name"],
            case_id=case["id"],
            executor_key="legacy-full",
            status="completed",
            verdict=True,
        )
    )

    partial = Run(name="Legacy partial", status="completed")
    partial.config = {"case_ids": [case["id"]]}
    session.add(partial)
    session.flush()
    assert partial.id is not None
    partial_item = RunItem(
        run_id=partial.id,
        set_id=eval_set["id"],
        set_name=eval_set["name"],
        case_id=case["id"],
        executor_key="legacy-partial",
        status="pending",
    )
    session.add(partial_item)
    session.commit()

    set_response = await client.get(f"/api/v1/sets/{eval_set['id']}/runs")
    rows = set_response.json()
    assert [(row["coverage"], row["is_partial"]) for row in rows] == [
        ("part of the set — exact coverage was not recorded", True),
        ("full set — exact size was not recorded", False),
    ]

    case_response = await client.get(f"/api/v1/cases/{case['id']}/run-items")
    pending = case_response.json()[0]
    assert pending["item_id"] == partial_item.id
    assert pending["output_preview"] is None
    assert pending["latency_ms"] is None
    assert pending["cost_usd"] is None
    assert pending["attempt_n"] is None
