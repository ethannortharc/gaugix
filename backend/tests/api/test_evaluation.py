"""Task-aware metrics API over frozen run inputs."""

from __future__ import annotations

import json

from sqlmodel import col, select

from gaugix.models.runs import Attempt, RunItem
from tests.api.test_cases import make_case, make_set
from tests.api.test_runs import make_fake_stack
from tests.api.test_set_nodes import create_node

PROFILE = {
    "kind": "binary_classification",
    "name": "Generic safety classifier",
    "truth": {"source": "tag", "key": "label"},
    "prediction": {"source": "output_json", "key": "verdict"},
    "score": {"source": "output_json", "key": "unsafe_score"},
    "category_truth": {"source": "tag", "key": "category"},
    "category_prediction": {"source": "output_json", "key": "category"},
    "positive_values": ["unsafe", "blocked"],
    "negative_values": ["safe", "allowed"],
    "positive_label": "blocked",
    "negative_label": "allowed",
    "false_positive_label": "Over-refusal",
}


async def test_run_metrics_use_the_frozen_generic_profile(client, session):
    stack = await make_fake_stack(client)
    eval_set = await make_set(client, name="Classify", evaluation_profile=PROFILE)
    specs = [
        ("Unsafe bias", ["label:unsafe", "category:bias"]),
        ("Unsafe crime", ["label:unsafe", "category:crime"]),
        ("Safe context", ["label:safe"]),
        ("Safe ordinary", ["label:safe"]),
    ]
    for title, tags in specs:
        await make_case(client, title=title, tags=tags, set_id=eval_set["id"])

    planned = await client.post(
        "/api/v1/runs",
        json={
            "set_ids": [eval_set["id"]],
            "executor_ids": [stack["executor"]["id"]],
            "start": False,
            "auto_score": False,
        },
    )
    assert planned.status_code == 201, planned.text
    run_id = planned.json()["id"]

    # Prove historical interpretation is frozen rather than read from the live
    # set when the report opens later.
    patched = await client.patch(
        f"/api/v1/sets/{eval_set['id']}",
        json={"evaluation_profile": {"kind": "standard"}},
    )
    assert patched.status_code == 200

    items = session.exec(
        select(RunItem).where(RunItem.run_id == run_id).order_by(col(RunItem.position))
    ).all()
    outputs = [
        {"verdict": "blocked", "category": "bias", "unsafe_score": 0.9},
        {"verdict": "allowed", "unsafe_score": 0.2},
        {"verdict": "blocked", "category": "bias", "unsafe_score": 0.8},
        {"verdict": "allowed", "unsafe_score": 0.1},
    ]
    for index, (item, output) in enumerate(zip(items, outputs, strict=True), start=1):
        item.status = "passed"
        session.add(item)
        session.add(
            Attempt(
                run_item_id=item.id or 0,
                n=1,
                status="ok",
                output_text=json.dumps(output),
                latency_ms=index * 10,
            )
        )
    session.commit()

    response = await client.get(f"/api/v1/runs/{run_id}/metrics")
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["slices"]) == 1
    summary = body["slices"][0]
    assert summary["profile"]["kind"] == "binary_classification"
    assert summary["confusion"] == {
        "tp": 1,
        "fp": 1,
        "fn": 1,
        "tn": 1,
        "positive_label": "blocked",
        "negative_label": "allowed",
    }
    metrics = {row["key"]: row for row in summary["metrics"]}
    assert metrics["recall"]["value"] == 0.5
    assert metrics["false_positive_rate"]["label"] == "Over-refusal"


async def test_node_metrics_roll_up_descendants_from_the_frozen_run_tree(client, session):
    stack = await make_fake_stack(client)
    eval_set = await make_set(client, name="Tree metrics")
    root = await create_node(client, eval_set["id"], "Safety")
    child = await create_node(client, eval_set["id"], "Multilingual", parent_id=root["id"])
    await make_case(client, title="Direct", set_id=eval_set["id"], node_id=root["id"])
    await make_case(client, title="Nested", set_id=eval_set["id"], node_id=child["id"])
    await make_case(client, title="Outside", set_id=eval_set["id"])
    planned = await client.post(
        "/api/v1/runs",
        json={
            "set_ids": [eval_set["id"]],
            "executor_ids": [stack["executor"]["id"]],
            "start": False,
        },
    )
    run_id = planned.json()["id"]
    items = session.exec(select(RunItem).where(RunItem.run_id == run_id)).all()
    for item in items:
        item.status = "passed"
        item.verdict = item.title != "Nested"
        session.add(item)
    session.commit()

    # Reorganising the live tree after planning must not change the rollup.
    await client.patch(
        f"/api/v1/sets/{eval_set['id']}/nodes/{child['id']}", json={"name": "Renamed"}
    )
    root_summary = (
        await client.get(f"/api/v1/runs/{run_id}/metrics", params={"node_id": root["id"]})
    ).json()["slices"][0]
    metrics = {metric["key"]: metric for metric in root_summary["metrics"]}
    assert root_summary["node_path"] == ["Safety"]
    assert root_summary["coverage"]["items"] == 2
    assert metrics["pass_rate"]["numerator"] == 1
    assert metrics["pass_rate"]["denominator"] == 2

    child_summary = (
        await client.get(f"/api/v1/runs/{run_id}/metrics", params={"node_id": child["id"]})
    ).json()["slices"][0]
    assert child_summary["node_path"] == ["Safety", "Multilingual"]
    assert child_summary["coverage"]["items"] == 1
