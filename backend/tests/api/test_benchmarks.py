"""Benchmark catalogue endpoints.

Every test here is offline. The `full` scope is the only path that can open a
connection, and the one test that exercises it asserts the *refusal* rather than
performing a download — a test suite that fetches a few megabytes from GitHub is
a test suite that fails on a train.
"""

from __future__ import annotations


async def test_the_catalogue_lists_every_benchmark_with_its_licence(client):
    response = await client.get("/api/v1/benchmarks")

    assert response.status_code == 200
    body = response.json()
    slugs = {entry["slug"] for entry in body}
    assert {"gsm8k", "mt-bench", "ifeval", "truthfulqa", "simpleqa", "humaneval"} <= slugs
    for entry in body:
        assert entry["licence"]
        assert entry["sample_size"] > 0
        assert entry["installed"] == []


async def test_detail_shows_the_caveats_and_the_exact_url_it_would_fetch(client):
    response = await client.get("/api/v1/benchmarks/gsm8k")

    body = response.json()
    assert body["caveats"], "a benchmark with no stated caveats is a marketing page"
    assert body["source"]["host"] == "raw.githubusercontent.com"
    assert body["source"]["url"].endswith("test.jsonl")
    # Real cases, built by the same adapter an install uses.
    assert body["sample_cases"][0]["reference"] == "18"


async def test_an_unknown_slug_is_a_404(client):
    response = await client.get("/api/v1/benchmarks/nope")
    assert response.status_code == 404


async def test_installing_the_sample_creates_a_runnable_set(client):
    response = await client.post("/api/v1/benchmarks/gsm8k/install", json={"scope": "sample"})

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["imported"] == 5
    assert body["set_name"] == "GSM8K (sample)"

    cases = (await client.get(f"/api/v1/sets/{body['set_id']}/cases")).json()
    assert len(cases) == 5
    # It arrives scored, or it is a pile of prompts rather than an eval.
    assert cases[0]["scoring"][0]["type"] == "python"

    eval_set = (await client.get(f"/api/v1/sets/{body['set_id']}")).json()
    assert "benchmark:gsm8k" in eval_set["tags"]


async def test_an_installed_benchmark_reports_itself_in_the_catalogue(client):
    installed = await client.post("/api/v1/benchmarks/gsm8k/install", json={"scope": "sample"})
    set_id = installed.json()["set_id"]

    entry = next(e for e in (await client.get("/api/v1/benchmarks")).json() if e["slug"] == "gsm8k")

    assert [s["id"] for s in entry["installed"]] == [set_id]
    assert entry["installed"][0]["case_count"] == 5


async def test_installing_twice_under_the_same_name_is_refused(client):
    await client.post("/api/v1/benchmarks/gsm8k/install", json={"scope": "sample"})
    again = await client.post("/api/v1/benchmarks/gsm8k/install", json={"scope": "sample"})

    assert again.status_code == 422
    assert "already exists" in again.json()["error"]["message"]


async def test_a_second_install_under_a_new_name_is_allowed(client):
    await client.post("/api/v1/benchmarks/gsm8k/install", json={"scope": "sample"})
    again = await client.post(
        "/api/v1/benchmarks/gsm8k/install",
        json={"scope": "sample", "set_name": "GSM8K second look"},
    )

    assert again.status_code == 201
    assert again.json()["set_name"] == "GSM8K second look"


async def test_humaneval_will_not_install_without_acknowledging_code_execution(client):
    """Scoring it runs model-written code on the host. That needs saying yes to."""
    refused = await client.post("/api/v1/benchmarks/humaneval/install", json={"scope": "sample"})

    assert refused.status_code == 422
    message = refused.json()["error"]["message"]
    assert "sandbox" in message and "accept_code_execution" in message
    assert (await client.get("/api/v1/sets")).json() == []

    accepted = await client.post(
        "/api/v1/benchmarks/humaneval/install",
        json={"scope": "sample", "accept_code_execution": True},
    )
    assert accepted.status_code == 201
    assert accepted.json()["imported"] == 5


async def test_preview_describes_the_install_without_writing_anything(client):
    response = await client.post("/api/v1/benchmarks/mt-bench/preview", json={"scope": "sample"})

    body = response.json()
    assert body["case_count"] == 5
    assert body["requires_judge"] is True
    assert any("sample" in w for w in body["warnings"])
    # Preview describes; it does not gate. The acknowledgement lives on install.
    assert (await client.get("/api/v1/sets")).json() == []


async def test_preview_of_a_full_install_names_the_host_it_would_contact(client):
    body = (await client.post("/api/v1/benchmarks/ifeval/preview", json={"scope": "full"})).json()

    assert body["source"]["host"] == "raw.githubusercontent.com"
    assert body["case_count"] == 541


async def test_preview_reports_a_name_clash_before_the_download(client):
    await client.post("/api/v1/benchmarks/gsm8k/install", json={"scope": "sample"})

    response = await client.post("/api/v1/benchmarks/gsm8k/preview", json={"scope": "sample"})

    assert response.status_code == 422
    assert "already exists" in response.json()["error"]["message"]


async def test_a_full_install_failing_to_reach_the_host_says_the_sample_still_works(
    client, monkeypatch
):
    """Offline is a normal state for a local-first tool, not a crash."""
    import httpx

    def refuse(*args, **kwargs):
        raise httpx.ConnectError("nope")

    monkeypatch.setattr(httpx.Client, "get", refuse)

    response = await client.post("/api/v1/benchmarks/gsm8k/install", json={"scope": "full"})

    assert response.status_code == 422
    message = response.json()["error"]["message"]
    assert "raw.githubusercontent.com" in message
    assert "sample" in message
    assert (await client.get("/api/v1/sets")).json() == []


# -- provenance and method fidelity --------------------------------------------


async def test_the_catalogue_says_whether_a_score_is_the_published_one(client):
    """ "We ran MT-Bench" and "we ran something MT-Bench shaped" must not look alike."""
    rows = (await client.get("/api/v1/benchmarks")).json()
    by_slug = {r["slug"]: r for r in rows}

    assert by_slug["gsm8k"]["method"]["fidelity"] == "official-compatible"
    assert by_slug["gsm8k"]["method"]["comparable"] is True
    # IFEval implements every official rule but approximates three NLP
    # components it cannot ship offline, so it does not claim comparability.
    assert by_slug["ifeval"]["method"]["comparable"] is False
    assert by_slug["mt-bench"]["method"]["fidelity"] == "gaugix-adaptation"
    assert by_slug["mt-bench"]["method"]["comparable"] is False
    for row in rows:
        assert row["method"]["deviations"], f"{row['slug']} claims no deviations at all"


async def test_ifeval_is_licensed_as_the_dataset_not_as_the_repository(client):
    """The questions are CC BY 4.0; Apache-2.0 covers google-research's source."""
    body = (await client.get("/api/v1/benchmarks/ifeval")).json()

    assert body["licence"] == "CC BY 4.0"
    assert "Apache-2.0" in body["licence_note"]


async def test_every_downloadable_source_pins_a_revision_or_a_checksum(client):
    """A `main`-tracking URL redefines the benchmark under you."""
    for entry in (await client.get("/api/v1/benchmarks")).json():
        body = (await client.get(f"/api/v1/benchmarks/{entry['slug']}")).json()
        source = body["source"]
        if source is None:
            continue
        assert source["revision"] or source["sha256"], f"{entry['slug']} pins nothing"
        assert source["expected_rows"] > 0


async def test_an_installed_set_records_where_it_came_from(client):
    """A set that cannot name its revision cannot support a claim about a model."""
    response = await client.post("/api/v1/benchmarks/gsm8k/install", json={"scope": "sample"})

    assert response.status_code == 201, response.text
    record = response.json()["provenance"]
    assert record["benchmark"] == "gsm8k"
    assert record["licence"] == "MIT"
    assert record["method_fidelity"] == "official-compatible"
    assert record["method_version"]
    assert record["installed_at"]
    assert record["case_count"] == response.json()["imported"]


async def test_truthfulqa_is_described_at_its_current_size_not_the_papers(client):
    """The repository holds 790 questions; the paper says 817."""
    body = (await client.get("/api/v1/benchmarks/truthfulqa")).json()

    assert body["full_size"] == 790
    assert body["source"]["expected_rows"] == 790


# -- provenance is visible and maintained --------------------------------------


async def test_a_set_reports_the_dataset_it_came_from(client):
    """Provenance recorded and never shown cannot prove anything."""
    install = await client.post("/api/v1/benchmarks/gsm8k/install", json={"scope": "sample"})
    set_id = install.json()["set_id"]

    body = (await client.get(f"/api/v1/sets/{set_id}")).json()

    record = body["provenance"]
    assert record["benchmark"] == "gsm8k"
    assert record["method_fidelity"] == "official-compatible"
    assert record["modified"] is False


async def test_a_hand_made_set_has_no_provenance_to_show(client):
    from tests.api.test_cases import make_set

    eval_set = await make_set(client, name="Mine")

    body = (await client.get(f"/api/v1/sets/{eval_set['id']}")).json()

    assert body["provenance"] == {}


async def test_adding_a_case_makes_a_benchmark_set_derived(client):
    """It may be a better eval than the original; it is not the benchmark."""
    install = await client.post("/api/v1/benchmarks/gsm8k/install", json={"scope": "sample"})
    set_id = install.json()["set_id"]

    await client.post(
        "/api/v1/cases",
        json={
            "title": "Mine",
            "input": [{"role": "user", "content": "hi"}],
            "set_id": set_id,
        },
    )
    body = (await client.get(f"/api/v1/sets/{set_id}")).json()

    assert body["provenance"]["modified"] is True
    assert "1 case(s) added" in body["provenance"]["modified_reasons"][0]


async def test_removing_a_case_makes_a_benchmark_set_derived(client):
    install = await client.post("/api/v1/benchmarks/gsm8k/install", json={"scope": "sample"})
    set_id = install.json()["set_id"]
    cases = (await client.get(f"/api/v1/sets/{set_id}/cases")).json()

    await client.post("/api/v1/cases/bulk/delete", json={"case_ids": [cases[0]["id"]]})
    body = (await client.get(f"/api/v1/sets/{set_id}")).json()

    assert body["provenance"]["modified"] is True
    assert "removed" in body["provenance"]["modified_reasons"][0]


async def test_a_run_freezes_the_dataset_it_measured(client):
    """A report has to name the revision months later; the set can change."""
    from tests.api.test_runs import make_fake_stack, wait_for_run

    install = await client.post("/api/v1/benchmarks/gsm8k/install", json={"scope": "sample"})
    set_id = install.json()["set_id"]
    stack = await make_fake_stack(client)
    created = await client.post(
        "/api/v1/runs",
        json={"set_ids": [set_id], "executor_ids": [stack["executor"]["id"]]},
    )
    run = await wait_for_run(client, created.json()["id"])

    frozen = run["config"]["sets"][0]["provenance"]
    assert frozen["benchmark"] == "gsm8k"
    assert frozen["method_version"]

    html = (await client.get(f"/api/v1/runs/{run['id']}/report")).text
    assert "Dataset —" in html
    assert "official-compatible" in html
