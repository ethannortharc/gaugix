"""Health endpoint + error envelope shape."""

from __future__ import annotations

from gaugix import __version__


async def test_health_reports_ok(client):
    response = await client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__
    assert body["db"] == "ok"
    assert body["data_dir"]


async def test_health_reports_configured_instance_id(client, monkeypatch):
    monkeypatch.setenv("GAUGIX_INSTANCE_ID", "hybrid-test")
    from gaugix.config import reset_settings_cache

    reset_settings_cache()
    try:
        response = await client.get("/api/health")
        assert response.status_code == 200
        assert response.json()["instance_id"] == "hybrid-test"
    finally:
        reset_settings_cache()


async def test_unknown_api_route_uses_the_error_envelope(client):
    response = await client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "not_found"
    assert isinstance(body["error"]["message"], str)


async def test_root_serves_the_ui_or_explains_where_it_is(client):
    """Both modes are legitimate: built (`make build`) serves the SPA, unbuilt hints."""
    response = await client.get("/")
    assert response.status_code == 200
    if response.headers["content-type"].startswith("application/json"):
        assert "health" in response.json()
    else:
        assert '<div id="root">' in response.text


async def test_unknown_api_route_stays_json_even_when_the_spa_is_built(client):
    """The SPA catch-all must never answer an /api path with HTML."""
    response = await client.get("/api/v1/cases/does-not-exist/nope")
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["error"]["code"] in {"not_found", "validation_error"}
