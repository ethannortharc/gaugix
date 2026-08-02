"""Artifacts end to end: a run produces them, the API serves them safely (PRD F6)."""

from __future__ import annotations

from tests.api.test_cases import make_set
from tests.api.test_runs import make_fake_stack, wait_for_run

CODE_ANSWER = (
    "Here is the fix:\n\n```python\ndef solve():\n    return 42\n```\n\n"
    "And the page:\n\n```html\n<h1>hi</h1>\n```\n"
)

WRITES_CODE = {"mode": "script", "default_response": CODE_ANSWER}


async def run_one_case(client, response_text: str | None = None):
    eval_set = await make_set(client, name="Coding")
    created_case = await client.post(
        "/api/v1/cases",
        json={
            "title": "write a solver",
            "input": [{"role": "user", "content": "write a solver"}],
            "set_id": eval_set["id"],
        },
    )
    assert created_case.status_code == 201
    config = {"mode": "script", "default_response": response_text or CODE_ANSWER}
    stack = await make_fake_stack(client, "coder", config)

    created = await client.post(
        "/api/v1/runs",
        json={"set_ids": [eval_set["id"]], "executor_ids": [stack["executor"]["id"]]},
    )
    run = await wait_for_run(client, created.json()["id"])
    items = (await client.get(f"/api/v1/runs/{run['id']}/items")).json()
    return run, items[0]


# -- capture -------------------------------------------------------------------


async def test_every_attempt_stores_its_raw_output(client):
    _, item = await run_one_case(client)

    artifacts = (await client.get(f"/api/v1/items/{item['id']}/artifacts")).json()

    raw = [a for a in artifacts if a["kind"] == "raw_output"]
    assert len(raw) == 1
    assert raw[0]["filename"] == "output.md"
    assert raw[0]["size_bytes"] > 0


async def test_fenced_blocks_are_extracted_as_typed_files(client):
    _, item = await run_one_case(client)

    artifacts = (await client.get(f"/api/v1/items/{item['id']}/artifacts")).json()

    blocks = sorted(
        (a for a in artifacts if a["kind"] == "code_block"), key=lambda a: a["block_index"]
    )
    assert [b["filename"] for b in blocks] == ["block-1.py", "block-2.html"]
    assert blocks[0]["language"] == "python"
    assert blocks[0]["mime"] == "text/x-python"


async def test_an_answer_with_no_code_produces_only_the_transcript(client):
    _, item = await run_one_case(client, response_text="Just prose, no code at all.")

    artifacts = (await client.get(f"/api/v1/items/{item['id']}/artifacts")).json()

    assert [a["kind"] for a in artifacts] == ["raw_output"]


# -- serving -------------------------------------------------------------------


async def test_artifact_content_round_trips(client):
    _, item = await run_one_case(client)
    artifacts = (await client.get(f"/api/v1/items/{item['id']}/artifacts")).json()
    block = next(a for a in artifacts if a["filename"] == "block-1.py")

    response = await client.get(f"/api/v1/artifacts/{block['id']}/content")

    assert response.status_code == 200
    assert response.text == "def solve():\n    return 42\n"


async def test_generated_html_is_never_served_as_html(client):
    """Same origin as the app: served as text/html it could call our own API."""
    _, item = await run_one_case(client)
    artifacts = (await client.get(f"/api/v1/items/{item['id']}/artifacts")).json()
    page = next(a for a in artifacts if a["filename"] == "block-2.html")

    response = await client.get(f"/api/v1/artifacts/{page['id']}/content")

    assert response.headers["content-type"].startswith("text/plain")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in response.headers["content-security-policy"]
    # The real type still travels, so the client can pick a renderer.
    assert response.headers["x-artifact-mime"] == "text/html"


async def test_downloading_an_artifact_is_an_attachment(client):
    _, item = await run_one_case(client)
    artifacts = (await client.get(f"/api/v1/items/{item['id']}/artifacts")).json()

    response = await client.get(
        f"/api/v1/artifacts/{artifacts[0]['id']}/content", params={"download": True}
    )

    assert "attachment" in response.headers["content-disposition"]
    assert response.headers["content-type"].startswith("application/octet-stream")


async def test_an_unknown_artifact_is_a_404(client):
    assert (await client.get("/api/v1/artifacts/9999/content")).status_code == 404
    assert (await client.get("/api/v1/artifacts/9999")).status_code == 404


# -- side by side (PRD F6.5) ---------------------------------------------------


async def test_side_by_side_returns_a_pane_per_item_in_order(client):
    eval_set = await make_set(client, name="Coding")
    await client.post(
        "/api/v1/cases",
        json={
            "title": "write a solver",
            "input": [{"role": "user", "content": "write a solver"}],
            "set_id": eval_set["id"],
        },
    )
    first = await make_fake_stack(client, "alpha", WRITES_CODE)
    second = await make_fake_stack(
        client, "beta", {"mode": "script", "default_response": "```go\nfunc main() {}\n```"}
    )

    created = await client.post(
        "/api/v1/runs",
        json={
            "set_ids": [eval_set["id"]],
            "executor_ids": [first["executor"]["id"], second["executor"]["id"]],
        },
    )
    run = await wait_for_run(client, created.json()["id"])
    items = (await client.get(f"/api/v1/runs/{run['id']}/items")).json()
    ids = [item["id"] for item in items]

    body = (await client.get("/api/v1/artifacts/compare", params={"item_id": ids})).json()

    assert [side["item_id"] for side in body["sides"]] == ids
    assert {side["executor_key"] for side in body["sides"]} == {
        first["executor"]["name"],
        second["executor"]["name"],
    }
    assert all(side["output_text"] for side in body["sides"])
    assert any(a["filename"] == "block-1.go" for a in body["sides"][1]["artifacts"])


async def test_side_by_side_refuses_fewer_than_two_panes(client):
    _, item = await run_one_case(client)

    response = await client.get("/api/v1/artifacts/compare", params={"item_id": [item["id"]]})

    assert response.status_code == 422
    assert "2 and 4" in response.json()["error"]["message"]


async def test_side_by_side_refuses_more_than_four_panes(client):
    _, item = await run_one_case(client)
    ids = [item["id"]] * 5

    response = await client.get("/api/v1/artifacts/compare", params={"item_id": ids})

    assert response.status_code == 422


async def test_side_by_side_with_an_unknown_item_is_a_404(client):
    _, item = await run_one_case(client)

    response = await client.get("/api/v1/artifacts/compare", params={"item_id": [item["id"], 9999]})

    assert response.status_code == 404


async def test_the_compare_route_is_not_swallowed_by_the_id_route(client):
    """`/artifacts/compare` must not be parsed as artifact_id="compare" (D-010)."""
    response = await client.get("/api/v1/artifacts/compare")
    # Refused for the right reason: not enough panes, not "no such artifact".
    assert response.status_code == 422


# -- executing a generated program (PRD F6.4) ----------------------------------


async def run_python_case(client):
    return await run_one_case(client, response_text='```python\nprint("hello from the model")\n```')


async def test_running_without_a_token_is_refused(client):
    """Gate G6: nothing starts a process without an explicit confirmation."""
    _, item = await run_python_case(client)
    artifacts = (await client.get(f"/api/v1/items/{item['id']}/artifacts")).json()
    script = next(a for a in artifacts if a["filename"].endswith(".py"))

    response = await client.post(
        f"/api/v1/artifacts/{script['id']}/exec", json={"confirm_token": ""}
    )

    assert response.status_code == 422
    assert "confirmation token" in response.json()["error"]["message"]


async def test_a_forged_token_is_refused(client):
    _, item = await run_python_case(client)
    artifacts = (await client.get(f"/api/v1/items/{item['id']}/artifacts")).json()
    script = next(a for a in artifacts if a["filename"].endswith(".py"))

    response = await client.post(
        f"/api/v1/artifacts/{script['id']}/exec", json={"confirm_token": "a" * 64}
    )

    assert response.status_code == 422


async def test_the_plan_shows_the_exact_command_and_warns(client):
    _, item = await run_python_case(client)
    artifacts = (await client.get(f"/api/v1/items/{item['id']}/artifacts")).json()
    script = next(a for a in artifacts if a["filename"].endswith(".py"))

    plan = (await client.get(f"/api/v1/artifacts/{script['id']}/exec-plan")).json()

    assert plan["argv"][0] == "python3"
    assert plan["argv"][-1].endswith(".py")
    assert plan["confirm_token"]
    # The warning must not imply protection that does not exist.
    assert "does not sandbox" in plan["warning"]


async def test_a_confirmed_run_executes_and_returns_its_output(client):
    _, item = await run_python_case(client)
    artifacts = (await client.get(f"/api/v1/items/{item['id']}/artifacts")).json()
    script = next(a for a in artifacts if a["filename"].endswith(".py"))

    plan = (await client.get(f"/api/v1/artifacts/{script['id']}/exec-plan")).json()
    result = (
        await client.post(
            f"/api/v1/artifacts/{script['id']}/exec",
            json={"confirm_token": plan["confirm_token"]},
        )
    ).json()

    assert result["exit_code"] == 0
    assert "hello from the model" in result["stdout"]
    assert result["timed_out"] is False


async def test_a_token_for_one_artifact_does_not_run_another(client):
    """The token is an HMAC over the command, not a general permission slip."""
    _, item = await run_one_case(
        client,
        response_text='```python\nprint("first")\n```\n\n```python\nprint("second")\n```',
    )
    artifacts = (await client.get(f"/api/v1/items/{item['id']}/artifacts")).json()
    scripts = sorted(
        (a for a in artifacts if a["filename"].endswith(".py")), key=lambda a: a["filename"]
    )

    plan = (await client.get(f"/api/v1/artifacts/{scripts[0]['id']}/exec-plan")).json()
    response = await client.post(
        f"/api/v1/artifacts/{scripts[1]['id']}/exec",
        json={"confirm_token": plan["confirm_token"]},
    )

    assert response.status_code == 422


async def test_an_unrunnable_artifact_is_refused_rather_than_guessed_at(client):
    _, item = await run_one_case(client, response_text="```\nplain text, no language\n```")
    artifacts = (await client.get(f"/api/v1/items/{item['id']}/artifacts")).json()
    block = next(a for a in artifacts if a["filename"].endswith(".txt"))

    response = await client.get(f"/api/v1/artifacts/{block['id']}/exec-plan")

    assert response.status_code == 422
    assert "will not guess" in response.json()["error"]["message"]
