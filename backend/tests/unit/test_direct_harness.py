"""DirectHarness structured HTTP-error capture.

The opt-in exists for gateways whose policy refusal is the result under test.
It must never turn an unrelated authentication or provider failure into output.
"""

from __future__ import annotations

import json

import httpx
import pytest

from gaugix.domain import (
    CaseSnapshot,
    HarnessError,
    InvokeContext,
    Message,
    ModelSnapshot,
    Provider,
    Role,
)
from gaugix.harness.direct import DirectHarness, validate_direct_harness_config


class ProviderHTTPError(Exception):
    def __init__(self, status_code: int, body: dict):
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code
        self.body = body


MODEL = ModelSnapshot(
    name="mt0",
    provider=Provider.openai_compatible,
    model_id="openrouter/qwen/qwen3.6-27b",
    base_url="http://gateway:8099/v1",
)
CASE = CaseSnapshot(
    title="blocked",
    input=[Message(role=Role.user, content="blocked text")],
)
CAPTURE = {
    "capture_http_errors": {
        "status_codes": [403],
        "error_codes": ["guardrails_blocked"],
    }
}
ADAPTED = {**CAPTURE, "output_adapter": "guardrail_verdict_v1"}


def use_transport(monkeypatch, handler):
    """Route the private HTTP client through an in-process httpx transport."""
    async_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)

    def client(**kwargs):
        return async_client(transport=transport, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)


async def test_captures_only_an_explicit_structured_policy_refusal(monkeypatch):
    import gaugix.harness.direct as direct

    body = {
        "is_mt0_error": True,
        "status_code": 403,
        "error": {
            "code": "guardrails_blocked",
            "type": "guardrails_violation",
            "param": {"rule_id": "guard-cls", "method": "model_classifier"},
        },
    }

    async def refuse(**_kwargs):
        raise ProviderHTTPError(403, body)

    monkeypatch.setattr(direct, "_openai_compatible_completion", refuse)
    result = await DirectHarness().invoke(CASE, MODEL, InvokeContext(harness_config=CAPTURE))

    assert json.loads(result.output_text) == body
    assert result.messages[-1]["role"] == "assistant"
    assert result.raw["captured_http_error"] == {
        "status_code": 403,
        "error_code": "guardrails_blocked",
        "body": body,
    }
    assert result.usage.latency_ms >= 0


async def test_guardrail_adapter_normalizes_a_captured_refusal(monkeypatch):
    import gaugix.harness.direct as direct

    body = {
        "type": "guardrails_violation",
        "error": {
            "code": "guardrails_blocked",
            "message": "blocked",
            "param": {
                "rule_id": "real-guard",
                "method": "model_classifier",
                "category": "Violent",
                "provider": "qwen",
            },
        },
    }

    async def refuse(**_kwargs):
        raise ProviderHTTPError(403, body)

    monkeypatch.setattr(direct, "_openai_compatible_completion", refuse)
    result = await DirectHarness().invoke(CASE, MODEL, InvokeContext(harness_config=ADAPTED))
    output = json.loads(result.output_text)

    assert output == {
        "action": "block",
        "category": "Violent",
        "completion": "",
        "error_code": "guardrails_blocked",
        "error_type": "guardrails_violation",
        "guard_provider": "qwen",
        "http_status": 403,
        "method": "model_classifier",
        "refusal": "blocked",
        "rule_category": None,
        "rule_id": "real-guard",
        "schema_version": "guardrail-verdict/v1",
        "stream": None,
        "tool_calls": [],
        "verdict": "blocked",
    }
    assert result.raw["captured_http_error"]["body"] == body


async def test_capture_path_keeps_successful_openai_compatible_calls_scoreable(monkeypatch):
    import gaugix.harness.direct as direct

    seen = {}

    async def complete(**kwargs):
        seen.update(kwargs)
        return {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 1},
        }

    monkeypatch.setenv("MT0_EVAL_VK", "local-secret")
    monkeypatch.setattr(direct, "_openai_compatible_completion", complete)
    config = {
        **CAPTURE,
        "request_headers_from_env": {"x-mt-vk": "MT0_EVAL_VK"},
    }

    result = await DirectHarness().invoke(CASE, MODEL, InvokeContext(harness_config=config))

    assert result.output_text == "ok"
    assert result.usage.prompt_tokens == 2
    assert result.usage.completion_tokens == 1
    assert seen["model"] == MODEL
    assert seen["env_headers"] == {"x-mt-vk": "local-secret"}
    assert "local-secret" not in json.dumps(result.raw)


async def test_guardrail_adapter_wraps_a_success_and_preserves_completion(monkeypatch):
    import gaugix.harness.direct as direct

    async def complete(**_kwargs):
        return {
            "choices": [{"message": {"content": "safe answer"}}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 2},
        }

    monkeypatch.setattr(direct, "_openai_compatible_completion", complete)
    result = await DirectHarness().invoke(CASE, MODEL, InvokeContext(harness_config=ADAPTED))
    output = json.loads(result.output_text)

    assert output["schema_version"] == "guardrail-verdict/v1"
    assert output["verdict"] == "allowed"
    assert output["http_status"] == 200
    assert output["completion"] == "safe answer"
    assert result.raw["source_output_text"] == "safe answer"
    assert result.messages[-1] == {"role": "assistant", "content": "safe answer"}


async def test_capture_path_matches_litellm_key_fallback_and_default_timeout(monkeypatch):
    seen = {}
    async_client = httpx.AsyncClient

    def handler(request):
        seen["request"] = request
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    class RecordingClient:
        def __init__(self, **kwargs):
            seen["timeout"] = kwargs["timeout"]
            self._client = async_client(transport=httpx.MockTransport(handler))

        async def __aenter__(self):
            return self._client

        async def __aexit__(self, *args):
            await self._client.aclose()

    import gaugix.harness.direct as direct

    monkeypatch.setenv("OPENAI_API_KEY", "fallback-key")
    monkeypatch.setattr(httpx, "AsyncClient", RecordingClient)
    result = await DirectHarness().invoke(CASE, MODEL, InvokeContext(harness_config=CAPTURE))

    assert result.output_text == "ok"
    assert seen["request"].headers["authorization"] == "Bearer fallback-key"
    assert seen["timeout"] == direct.DEFAULT_TIMEOUT_S


async def test_real_http_path_captures_structured_403_and_preserves_header_precedence(
    monkeypatch,
):
    body = {
        "status_code": 403,
        "error": {
            "code": "guardrails_blocked",
            "param": {"rule_id": "guard-cls", "method": "model_classifier"},
        },
    }
    seen = {}

    def handler(request):
        seen["request"] = request
        return httpx.Response(403, json=body)

    use_transport(monkeypatch, handler)
    monkeypatch.setenv("MT0_EVAL_VK", "environment-vk")
    monkeypatch.setenv("UPSTREAM_KEY", "profile-key")
    model = MODEL.model_copy(
        update={
            "model_id": "openai/openrouter/qwen/qwen3.6-27b",
            "api_key_env": "UPSTREAM_KEY",
            "params": {
                "extra_headers": {
                    "X-MT-VK": "configured-vk",
                    "Authorization": "Bearer configured-key",
                }
            },
        }
    )
    config = {
        **CAPTURE,
        "request_headers_from_env": {"x-mt-vk": "MT0_EVAL_VK"},
    }

    result = await DirectHarness().invoke(CASE, model, InvokeContext(harness_config=config))

    request = seen["request"]
    assert request.url == "http://gateway:8099/v1/chat/completions"
    assert request.headers["x-mt-vk"] == "environment-vk"
    assert request.headers["authorization"] == "Bearer configured-key"
    payload = json.loads(request.content)
    assert payload["model"] == "openrouter/qwen/qwen3.6-27b"
    assert "extra_headers" not in payload
    assert json.loads(result.output_text) == body


async def test_real_http_path_keeps_unstructured_403_as_provider_error(monkeypatch):
    def handler(_request):
        return httpx.Response(403, text="ordinary forbidden")

    use_transport(monkeypatch, handler)

    with pytest.raises(HarnessError) as exc:
        await DirectHarness().invoke(CASE, MODEL, InvokeContext(harness_config=CAPTURE))

    assert exc.value.kind == "provider_error"
    assert exc.value.retryable is False


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504, 529])
async def test_real_http_path_retries_transient_statuses(monkeypatch, status):
    def handler(_request):
        return httpx.Response(status, json={"error": {"code": "upstream_failure"}})

    use_transport(monkeypatch, handler)

    with pytest.raises(HarnessError) as exc:
        await DirectHarness().invoke(CASE, MODEL, InvokeContext(harness_config=CAPTURE))

    assert exc.value.kind == "provider_error"
    assert exc.value.retryable is True


async def test_real_http_path_retries_connection_failures(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("gateway unavailable", request=request)

    use_transport(monkeypatch, handler)

    with pytest.raises(HarnessError) as exc:
        await DirectHarness().invoke(CASE, MODEL, InvokeContext(harness_config=CAPTURE))

    assert exc.value.retryable is True


@pytest.mark.parametrize(
    "model",
    [
        MODEL.model_copy(update={"base_url": None}),
        MODEL.model_copy(update={"params": {"extra_headers": "not-an-object"}}),
    ],
)
async def test_capture_path_preserves_configuration_errors(model):
    with pytest.raises(HarnessError) as exc:
        await DirectHarness().invoke(CASE, model, InvokeContext(harness_config=CAPTURE))

    assert exc.value.kind == "config"
    assert not str(exc.value).startswith("HarnessError:")


@pytest.mark.parametrize(
    ("status", "code"),
    [(401, "guardrails_blocked"), (403, "forbidden"), (429, "guardrails_blocked")],
)
async def test_unlisted_provider_errors_remain_execution_errors(monkeypatch, status, code):
    import gaugix.harness.direct as direct

    async def refuse(**_kwargs):
        raise ProviderHTTPError(status, {"error": {"code": code}})

    monkeypatch.setattr(direct, "_openai_compatible_completion", refuse)
    with pytest.raises(HarnessError) as exc:
        await DirectHarness().invoke(CASE, MODEL, InvokeContext(harness_config=CAPTURE))

    assert exc.value.kind == "provider_error"


@pytest.mark.parametrize(
    "config",
    [
        {"capture_http_errors": True},
        {"capture_http_errors": {"status_codes": [], "error_codes": ["x"]}},
        {"capture_http_errors": {"status_codes": [200], "error_codes": ["x"]}},
        {"capture_http_errors": {"status_codes": [403], "error_codes": []}},
    ],
)
def test_capture_allowlist_rejects_unsafe_or_ambiguous_config(config):
    with pytest.raises(HarnessError) as exc:
        validate_direct_harness_config(config)

    assert exc.value.kind == "config"


def test_direct_harness_rejects_an_unknown_output_adapter():
    with pytest.raises(HarnessError) as exc:
        validate_direct_harness_config({"output_adapter": "magic"})

    assert exc.value.kind == "config"
    assert "guardrail_verdict_v1" in str(exc.value)


async def test_request_headers_are_resolved_from_environment_without_entering_raw_result(
    monkeypatch,
):
    import litellm

    seen = {}

    class MessageResult:
        content = "ok"

    class Choice:
        message = MessageResult()

    class UsageResult:
        prompt_tokens = 2
        completion_tokens = 1

    class Response:
        choices = [Choice()]
        usage = UsageResult()

    async def complete(**kwargs):
        seen.update(kwargs)
        return Response()

    monkeypatch.setenv("MT0_EVAL_VK", "local-secret")
    monkeypatch.setattr(litellm, "acompletion", complete)
    config = {"request_headers_from_env": {"x-mt-vk": "MT0_EVAL_VK"}}
    result = await DirectHarness().invoke(CASE, MODEL, InvokeContext(harness_config=config))

    assert seen["extra_headers"] == {"x-mt-vk": "local-secret"}
    assert "local-secret" not in json.dumps(result.raw)


def test_request_header_config_rejects_literal_values_and_invalid_names():
    for config in (
        {"request_headers_from_env": {"bad header": "MT0_EVAL_VK"}},
        {"request_headers_from_env": {"x-mt-vk": "literal secret"}},
    ):
        with pytest.raises(HarnessError):
            validate_direct_harness_config(config)


async def test_direct_harness_profile_api_accepts_the_explicit_gateway_policy(client):
    response = await client.post(
        "/api/v1/harness-profiles",
        json={
            "name": "policy-gateway",
            "kind": "direct",
            "config": {
                **CAPTURE,
                "request_headers_from_env": {"x-mt-vk": "MT0_EVAL_VK"},
            },
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["config"]["capture_http_errors"] == CAPTURE["capture_http_errors"]


async def test_direct_harness_profile_api_rejects_an_ambiguous_capture_policy(client):
    response = await client.post(
        "/api/v1/harness-profiles",
        json={
            "name": "unsafe-policy",
            "kind": "direct",
            "config": {
                "capture_http_errors": {
                    "status_codes": [403],
                    "error_codes": [],
                }
            },
        },
    )

    assert response.status_code == 422
    assert "non-empty string list" in response.json()["error"]["message"]
