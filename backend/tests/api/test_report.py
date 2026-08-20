"""Report export: self-contained, offline, and faithful to the data (PRD F5.5, gate G5)."""

from __future__ import annotations

import re

from sqlmodel import select

from tests.api.test_cases import make_set
from tests.api.test_compare import (
    ALLOW_SCORER,
    ALLOWS_EVERYTHING,
    BLOCK_SCORER,
    BLOCKS_EVERYTHING,
    fixture,
    make_case,
    run_both,
)
from tests.api.test_runs import make_fake_stack, wait_for_run

#: Anything that would make the file need a network to render. XML namespace
#: URIs are not fetched by a browser, so they are explicitly allowed.
EXTERNAL_REFERENCE = re.compile(
    r"""(?:src|href)\s*=\s*["']\s*(?:https?:)?//|url\(\s*["']?\s*(?:https?:)?//""",
    re.IGNORECASE,
)


def tile_value(html: str, label: str) -> str:
    """Read one headline tile's value out of the rendered report."""
    match = re.search(
        rf'<div class="label">{re.escape(label)}</div>\s*'
        rf'<div class="value[^"]*">(.*?)</div>',
        html,
        re.IGNORECASE | re.DOTALL,
    )
    return match.group(1).strip() if match else ""


async def report_for_run(client, run_id: int) -> str:
    response = await client.get(f"/api/v1/runs/{run_id}/report")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/html")
    return str(response.text)


# -- the offline contract ------------------------------------------------------


async def test_a_run_report_has_no_external_references(client):
    """Gate G5: the file must open on a laptop with no internet, forever."""
    env = await fixture(client)
    run = await run_both(client, env)

    html = await report_for_run(client, run["id"])

    assert EXTERNAL_REFERENCE.search(html) is None, "report reaches out to the network"
    assert "xmlns=" in html  # the SVG namespace URI is fine and must not be stripped


async def test_a_run_report_inlines_its_styles_and_charts(client):
    env = await fixture(client)
    run = await run_both(client, env)

    html = await report_for_run(client, run["id"])

    assert "<style>" in html
    assert "<svg" in html
    assert "<link" not in html
    assert "@import" not in html


async def test_a_comparison_report_has_no_external_references(client):
    env = await fixture(client)
    first = await run_both(client, env)
    second = await run_both(client, env)

    response = await client.get(
        "/api/v1/compare/report",
        params={"run_id": [first["id"], second["id"]], "baseline_run_id": first["id"]},
    )

    assert response.status_code == 200
    assert EXTERNAL_REFERENCE.search(response.text) is None


async def test_the_report_downloads_as_a_file(client):
    env = await fixture(client)
    run = await run_both(client, env)

    response = await client.get(f"/api/v1/runs/{run['id']}/report")

    assert "attachment" in response.headers["content-disposition"]
    assert f"gaugix-run-{run['id']}.html" in response.headers["content-disposition"]


# -- the data contract ---------------------------------------------------------


async def test_the_report_numbers_match_the_api(client):
    """Pretty for style, fair for content — the report cannot flatter the run."""
    env = await fixture(client)
    run = await run_both(client, env)

    board = (await client.get("/api/v1/compare/leaderboard", params={"run_id": run["id"]})).json()
    html = await report_for_run(client, run["id"])

    for label, expected in (
        ("Pass rate", f"{board['totals']['pass_rate']:g}%"),
        ("Items", str(board["totals"]["items"])),
    ):
        assert tile_value(html, label) == expected, label
    for row in board["rows"]:
        assert row["executor_key"] in html


async def test_no_tile_renders_a_python_repr(client):
    """`{{ totals.items }}` in Jinja is dict.items — the method, not the count.

    It rendered as "<built-in method items of dict object at 0x…>" in a headline
    tile. Any key colliding with a dict method has the same trap, so this guards
    the whole section rather than that one field.
    """
    env = await fixture(client)
    run = await run_both(client, env)

    html = await report_for_run(client, run["id"])

    assert "built-in method" not in html
    assert "object at 0x" not in html
    for label in ("Pass rate", "Items", "Mean score", "Cost", "Tokens"):
        value = tile_value(html, label)
        assert value and "<" not in value, f"{label} tile rendered {value!r}"


async def test_the_report_names_every_executor_it_measured(client):
    env = await fixture(client)
    run = await run_both(client, env)

    html = await report_for_run(client, run["id"])

    assert env["strict"]["name"] in html
    assert env["lenient"]["name"] in html
    assert "Methodology" in html


async def test_the_report_lists_the_failures_rather_than_hiding_them(client):
    env = await fixture(client)
    run = await run_both(client, env)

    html = await report_for_run(client, run["id"])

    # Each executor gets exactly two cases wrong in this fixture.
    assert "What failed" in html
    assert "benign one" in html
    assert "Expected result" in html
    assert "Actual result" in html
    assert "Why it failed" in html
    assert ": None" not in html
    assert "Frozen case and scoring configuration" in html
    assert "Frozen executor and captured invocation evidence" in html


async def test_the_report_redacts_literal_credentials_from_frozen_executor(client):
    secret = "sk-test-report-secret-123456"
    eval_set = await make_set(client, name="Secret-safe report")
    await make_case(client, eval_set["id"], "must fail", BLOCK_SCORER)
    stack = await make_fake_stack(
        client,
        "secret-safe",
        model_params={
            "extra_headers": {
                "Authorization": f"Bearer {secret}",
                "X-MT-VK": "literal-vk-secret",
            }
        },
    )
    created = await client.post(
        "/api/v1/runs",
        json={"set_ids": [eval_set["id"]], "executor_ids": [stack["executor"]["id"]]},
    )
    run = created.json()
    await wait_for_run(client, run["id"])

    html = await report_for_run(client, run["id"])

    assert secret not in html
    assert "literal-vk-secret" not in html
    assert "[REDACTED]" in html


async def test_the_report_redacts_credentials_from_case_title_and_tags(client):
    secret = "sk-report-case-metadata-secret-123456"
    eval_set = await make_set(client, name="Secret-safe case metadata")
    created = await client.post(
        "/api/v1/cases",
        json={
            "title": f"must fail api_key={secret}",
            "input": [{"role": "user", "content": "safe input"}],
            "tags": [f"credential:{secret}"],
            "scoring": BLOCK_SCORER,
            "set_id": eval_set["id"],
        },
    )
    assert created.status_code == 201, created.text
    stack = await make_fake_stack(client, "metadata-safe", ALLOWS_EVERYTHING)
    run = (
        await client.post(
            "/api/v1/runs",
            json={"set_ids": [eval_set["id"]], "executor_ids": [stack["executor"]["id"]]},
        )
    ).json()
    await wait_for_run(client, run["id"])

    html = await report_for_run(client, run["id"])

    assert secret not in html
    assert "[REDACTED]" in html


async def test_the_report_redacts_derived_score_rationales(client, session):
    from gaugix.models.scores import Score

    secret = "sk-report-rationale-secret-123456"
    eval_set = await make_set(client, name="Secret-safe rationale")
    await make_case(client, eval_set["id"], "must fail", BLOCK_SCORER)
    stack = await make_fake_stack(client, "rationale-safe")
    run = (
        await client.post(
            "/api/v1/runs",
            json={"set_ids": [eval_set["id"]], "executor_ids": [stack["executor"]["id"]]},
        )
    ).json()
    await wait_for_run(client, run["id"])
    score = session.exec(select(Score).where(Score.run_item_id > 0)).one()
    score.rationale = f"provider quoted {secret}"
    session.add(score)
    session.commit()

    html = await report_for_run(client, run["id"])

    assert secret not in html
    assert "[REDACTED]" in html


async def test_the_report_autoescapes_hostile_model_output(client):
    hostile = "</pre><script>window.pwned=1</script>"
    eval_set = await make_set(client, name="Hostile markup")
    await make_case(client, eval_set["id"], "must fail", BLOCK_SCORER)
    stack = await make_fake_stack(
        client,
        "hostile-output",
        {"mode": "script", "default_response": hostile},
    )
    run = (
        await client.post(
            "/api/v1/runs",
            json={"set_ids": [eval_set["id"]], "executor_ids": [stack["executor"]["id"]]},
        )
    ).json()
    await wait_for_run(client, run["id"])

    html = await report_for_run(client, run["id"])

    assert hostile not in html
    assert "&lt;script&gt;window.pwned=1&lt;/script&gt;" in html


async def test_a_self_judging_setup_is_disclosed_in_the_report(client):
    """A reader has to be able to see that a model graded its own output."""
    env = await fixture(client)
    run = await run_both(client, env)

    html = await report_for_run(client, run["id"])

    assert "grading its own output" in html or "scoring its own output" in html


async def test_the_report_says_how_pass_rate_was_computed(client):
    env = await fixture(client)
    run = await run_both(client, env)

    html = await report_for_run(client, run["id"])

    assert "passed ÷ scored" in html


async def test_the_report_includes_metrics_from_the_frozen_generic_profile(client):
    profile = {
        "kind": "binary_classification",
        "name": "Generic policy classifier",
        "truth": {"source": "tag", "key": "label"},
        "prediction": {"source": "output_json", "key": "verdict"},
        "positive_values": ["positive", "blocked"],
        "negative_values": ["negative", "allowed"],
        "positive_label": "blocked",
        "negative_label": "allowed",
        "false_positive_label": "Benign false-positive rate",
    }
    eval_set = await make_set(client, name="Policy classification", evaluation_profile=profile)
    for title, label in (("positive case", "positive"), ("negative case", "negative")):
        created = await client.post(
            "/api/v1/cases",
            json={
                "title": title,
                "input": [{"role": "user", "content": title}],
                "tags": [f"label:{label}"],
                "set_id": eval_set["id"],
            },
        )
        assert created.status_code == 201
    stack = await make_fake_stack(
        client,
        "policy",
        {"mode": "script", "default_response": '{"verdict":"blocked"}'},
    )
    created = await client.post(
        "/api/v1/runs",
        json={"set_ids": [eval_set["id"]], "executor_ids": [stack["executor"]["id"]]},
    )
    run = await wait_for_run(client, created.json()["id"])

    html = await report_for_run(client, run["id"])
    assert "Evaluation profile metrics" in html
    assert "Generic policy classifier" in html
    assert "Precision" in html
    assert "Benign false-positive rate" in html
    assert "Confusion matrix" in html


async def test_an_unscored_item_is_shown_as_unscored_not_failed(client):
    eval_set = await make_set(client, name="Half measured")
    await make_case(client, eval_set["id"], "no scorers here", [])
    await make_case(client, eval_set["id"], "jailbreak one", BLOCK_SCORER)
    stack = await make_fake_stack(client, "strict", BLOCKS_EVERYTHING)

    created = await client.post(
        "/api/v1/runs",
        json={"set_ids": [eval_set["id"]], "executor_ids": [stack["executor"]["id"]]},
    )
    run = await wait_for_run(client, created.json()["id"])

    html = await report_for_run(client, run["id"])

    assert "1 unscored" in html
    assert "an unscored item is not a failure" in html
    # 1 of 1 scored items passed, so the headline is 100% — not 50%.
    assert "100%" in html


async def test_a_comparison_report_shows_the_regression_diff(client):
    eval_set = await make_set(client, name="Guardrails")
    keeper = await make_case(client, eval_set["id"], "jailbreak one", BLOCK_SCORER)
    await make_case(client, eval_set["id"], "jailbreak two", BLOCK_SCORER)
    stack = await make_fake_stack(client, "strict", BLOCKS_EVERYTHING)
    executor_id = stack["executor"]["id"]

    baseline = await wait_for_run(
        client,
        (
            await client.post(
                "/api/v1/runs", json={"set_ids": [eval_set["id"]], "executor_ids": [executor_id]}
            )
        ).json()["id"],
    )
    await client.patch(f"/api/v1/cases/{keeper['id']}", json={"scoring": ALLOW_SCORER})
    current = await wait_for_run(
        client,
        (
            await client.post(
                "/api/v1/runs", json={"set_ids": [eval_set["id"]], "executor_ids": [executor_id]}
            )
        ).json()["id"],
    )

    response = await client.get(
        "/api/v1/compare/report",
        params={"run_id": [current["id"], baseline["id"]], "baseline_run_id": baseline["id"]},
    )

    html = response.text
    assert "Against baseline" in html
    assert "Regressions" in html
    assert "jailbreak one" in html
    assert "Expected result" in html
    assert "Actual result" in html
    assert "Frozen case and scoring configuration" in html


async def test_comparison_report_and_apis_redact_case_titles(client):
    secret = "sk-comparison-title-secret-123456"
    eval_set = await make_set(client, name="Secret-safe comparison")
    case = await make_case(client, eval_set["id"], f"regression api_key={secret}", BLOCK_SCORER)
    stack = await make_fake_stack(client, "comparison-safe", BLOCKS_EVERYTHING)
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
    patched = await client.patch(f"/api/v1/cases/{case['id']}", json={"scoring": ALLOW_SCORER})
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
    report_params = {
        "run_id": [baseline["id"], current["id"]],
        "baseline_run_id": baseline["id"],
    }

    report = await client.get("/api/v1/compare/report", params=report_params)
    diff = await client.get(
        "/api/v1/compare/diff",
        params={"run_id": current["id"], "baseline_run_id": baseline["id"]},
    )
    matrix = await client.get(
        "/api/v1/compare/matrix", params={"run_id": [baseline["id"], current["id"]]}
    )

    assert report.status_code == diff.status_code == matrix.status_code == 200
    for response in (report, diff, matrix):
        assert secret not in response.text
        assert "[REDACTED]" in response.text


async def test_a_report_for_a_run_that_does_not_exist_is_a_404(client):
    response = await client.get("/api/v1/runs/9999/report")
    assert response.status_code == 404


async def test_a_report_for_an_empty_run_still_renders(client):
    """Loading and empty states matter in an export too — it must not 500."""
    eval_set = await make_set(client, name="Nothing here")
    stack = await make_fake_stack(client, "strict", BLOCKS_EVERYTHING)
    created = await client.post(
        "/api/v1/runs",
        json={"set_ids": [eval_set["id"]], "executor_ids": [stack["executor"]["id"]]},
    )
    if created.status_code != 201:
        return  # an empty set is refused at creation; nothing to assert
    run = await wait_for_run(client, created.json()["id"])

    html = await report_for_run(client, run["id"])
    assert "Gaugix" in html
