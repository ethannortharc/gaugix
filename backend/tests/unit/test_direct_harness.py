"""DirectHarness structured HTTP-error capture.

The opt-in exists for gateways whose policy refusal is the result under test.
It must never turn an unrelated authentication or provider failure into output.
"""

from __future__ import annotations

import json

import httpx
import pytest

from gaugix.config import reset_settings_cache
from gaugix.domain import (
    CaseSnapshot,
    HarnessError,
    InvokeContext,
    Message,
    ModelSnapshot,
    Pricing,
    Provider,
    Role,
)
from gaugix.harness.direct import (
    DirectHarness,
    case_request_overrides,
    validate_direct_harness_config,
)


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
    assert result.usage.cost_usd == 0.0


def test_deep_case_directive_is_a_single_config_error_not_a_process_error():
    nested = "[" * 1100 + "]" * 1100
    messages = [{"role": "system", "content": f'@gaugix {{"tools": {nested}}}'}]

    with pytest.raises(HarnessError) as exc:
        case_request_overrides(messages, {"allow_case_request_overrides": True})

    assert exc.value.kind == "config"
    assert exc.value.retryable is False


async def test_capture_http_errors_rejects_non_openai_compatible_profiles():
    model = MODEL.model_copy(update={"provider": Provider.openai})

    with pytest.raises(HarnessError) as exc:
        await DirectHarness().invoke(CASE, model, InvokeContext(harness_config=CAPTURE))

    assert exc.value.kind == "config"
    assert "openai_compatible" in str(exc.value)


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


async def test_case_request_directive_enables_stream_without_reaching_provider_messages(
    monkeypatch,
):
    import gaugix.harness.direct as direct

    seen = {}

    async def complete(**kwargs):
        seen.update(kwargs)
        return {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }

    case = CASE.model_copy(
        update={
            "input": [
                Message(
                    role=Role.system,
                    content='@gaugix {"stream": true, "max_tokens": 17}',
                ),
                Message(role=Role.user, content="hello"),
            ]
        }
    )
    monkeypatch.setattr(direct, "_openai_compatible_completion", complete)
    config = {**ADAPTED, "allow_case_request_overrides": True}

    result = await DirectHarness().invoke(case, MODEL, InvokeContext(harness_config=config))

    assert seen["params"]["stream"] is True
    assert seen["params"]["max_tokens"] == 17
    assert seen["messages"] == [{"role": "user", "content": "hello"}]
    assert json.loads(result.output_text)["verdict"] == "allowed"


async def test_stream_directive_uses_real_http_path_without_error_capture(monkeypatch):
    import gaugix.harness.direct as direct

    seen = {}

    async def complete(**kwargs):
        seen.update(kwargs)
        return {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            "_gaugix_stream": {"chunks": 1, "first_delta_ms": 1, "interrupted": False},
            "_gaugix_stream_error": None,
        }

    case = CASE.model_copy(
        update={
            "input": [
                Message(role=Role.system, content='@gaugix {"stream": true}'),
                Message(role=Role.user, content="hello"),
            ]
        }
    )
    monkeypatch.setattr(direct, "_openai_compatible_completion", complete)

    result = await DirectHarness().invoke(
        case,
        MODEL,
        InvokeContext(
            harness_config={
                "allow_case_request_overrides": True,
                "output_adapter": "guardrail_verdict_v1",
            }
        ),
    )

    assert seen["params"]["stream"] is True
    assert json.loads(result.output_text)["completion"] == "ok"


async def test_tool_calls_are_preserved_in_raw_without_output_adapter(monkeypatch):
    import litellm

    async def complete(**_kwargs):
        return {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "type": "function",
                                "function": {
                                    "name": "lookup",
                                    "arguments": '{"id":42}',
                                },
                            }
                        ],
                    }
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }

    monkeypatch.setattr(litellm, "acompletion", complete)
    result = await DirectHarness().invoke(CASE, MODEL, InvokeContext(harness_config={}))

    assert result.raw["tool_calls"] == [
        {
            "id": "call-1",
            "name": "lookup",
            "arguments": '{"id":42}',
        }
    ]


async def test_stream_directive_rejects_non_openai_compatible_profiles():
    case = CASE.model_copy(
        update={
            "input": [
                Message(role=Role.system, content='@gaugix {"stream": true}'),
                Message(role=Role.user, content="hello"),
            ]
        }
    )
    model = MODEL.model_copy(update={"provider": Provider.anthropic})

    with pytest.raises(HarnessError) as exc:
        await DirectHarness().invoke(
            case,
            model,
            InvokeContext(harness_config={"allow_case_request_overrides": True}),
        )

    assert exc.value.kind == "config"
    assert "OpenAI-compatible" in str(exc.value)


async def test_case_request_directive_requires_the_explicit_profile_opt_in():
    case = CASE.model_copy(
        update={
            "input": [
                Message(role=Role.system, content='@gaugix {"stream": true}'),
                Message(role=Role.user, content="hello"),
            ]
        }
    )

    with pytest.raises(HarnessError) as exc:
        await DirectHarness().invoke(case, MODEL, InvokeContext(harness_config={}))

    assert exc.value.kind == "config"
    assert exc.value.retryable is False
    assert "allow_case_request_overrides=true" in str(exc.value)


async def test_case_request_directive_supports_strict_output_and_declared_tools(
    monkeypatch,
):
    import gaugix.harness.direct as direct

    seen = {}

    async def complete(**kwargs):
        seen.update(kwargs)
        return {
            "choices": [{"message": {"content": '{"payload":"fixed"}'}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }

    tool_name = "realevaltools-echo_args"
    directive = {
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "exact_payload",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {"payload": {"const": "fixed"}},
                    "required": ["payload"],
                    "additionalProperties": False,
                },
            },
        },
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": "Echo a fixed payload",
                    "strict": True,
                    "parameters": {
                        "type": "object",
                        "properties": {"payload": {"const": "fixed"}},
                        "required": ["payload"],
                        "additionalProperties": False,
                    },
                },
            }
        ],
        "tool_choice": {"type": "function", "function": {"name": tool_name}},
    }
    case = CASE.model_copy(
        update={
            "input": [
                Message(
                    role=Role.system,
                    content="@gaugix " + json.dumps(directive),
                ),
                Message(role=Role.user, content="produce the required payload"),
            ]
        }
    )
    monkeypatch.setattr(direct, "_openai_compatible_completion", complete)

    await DirectHarness().invoke(
        case,
        MODEL,
        InvokeContext(harness_config={**ADAPTED, "allow_case_request_overrides": True}),
    )

    assert seen["params"]["response_format"] == directive["response_format"]
    assert seen["params"]["tools"] == directive["tools"]
    assert seen["params"]["tool_choice"] == directive["tool_choice"]
    assert seen["messages"] == [{"role": "user", "content": "produce the required payload"}]


async def test_case_request_directive_allows_tool_choice_none_without_tools(monkeypatch):
    import gaugix.harness.direct as direct

    seen = {}

    async def complete(**params):
        seen.update(params)
        return {"choices": [{"message": {"content": "safe"}}]}

    case = CASE.model_copy(
        update={
            "input": [
                Message(role=Role.system, content='@gaugix {"tool_choice": "none"}'),
                Message(role=Role.user, content="hello"),
            ]
        }
    )
    monkeypatch.setattr(direct, "_openai_compatible_completion", complete)

    await DirectHarness().invoke(
        case,
        MODEL,
        InvokeContext(harness_config={**ADAPTED, "allow_case_request_overrides": True}),
    )

    assert seen["params"]["tool_choice"] == "none"
    assert "tools" not in seen["params"]
    assert seen["messages"] == [{"role": "user", "content": "hello"}]


@pytest.mark.parametrize(
    "directive",
    [
        {"tool_choice": "required"},
        {
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "declared",
                        "parameters": {"type": "object"},
                    },
                }
            ],
            "tool_choice": {
                "type": "function",
                "function": {"name": "undeclared"},
            },
        },
        {
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "loose",
                    "strict": False,
                    "schema": {"type": "object"},
                },
            }
        },
        {
            "tools": [
                {
                    "type": "mcp",
                    "server_url": "https://untrusted.invalid/mcp",
                }
            ]
        },
        {
            "tools": [
                {
                    "type": "web_search",
                    "function": {
                        "name": "declared",
                        "parameters": {"type": "object"},
                    },
                }
            ]
        },
        {
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "declared",
                        "parameters": {"type": "object"},
                    },
                }
            ],
            "tool_choice": {
                "type": "custom",
                "function": {"name": "declared"},
            },
        },
    ],
)
async def test_case_request_directive_rejects_unsafe_structured_overrides(directive):
    case = CASE.model_copy(
        update={
            "input": [
                Message(
                    role=Role.system,
                    content="@gaugix " + json.dumps(directive),
                ),
                Message(role=Role.user, content="hello"),
            ]
        }
    )

    with pytest.raises(HarnessError) as exc:
        await DirectHarness().invoke(
            case,
            MODEL,
            InvokeContext(harness_config={**ADAPTED, "allow_case_request_overrides": True}),
        )

    assert exc.value.kind == "config"


async def test_case_request_directive_rejects_credential_or_url_overrides():
    case = CASE.model_copy(
        update={
            "input": [
                Message(
                    role=Role.system,
                    content='@gaugix {"api_key": "secret", "base_url": "https://evil.invalid"}',
                ),
                Message(role=Role.user, content="hello"),
            ]
        }
    )

    with pytest.raises(HarnessError) as exc:
        await DirectHarness().invoke(
            case,
            MODEL,
            InvokeContext(harness_config={**ADAPTED, "allow_case_request_overrides": True}),
        )

    assert exc.value.kind == "config"
    assert "unsupported keys" in str(exc.value)


async def test_case_request_directive_rejects_oversized_json_before_parsing():
    case = CASE.model_copy(
        update={
            "input": [
                Message(
                    role=Role.system,
                    content='@gaugix {"padding":"' + ("x" * 33_000) + '"}',
                ),
                Message(role=Role.user, content="hello"),
            ]
        }
    )

    with pytest.raises(HarnessError) as exc:
        await DirectHarness().invoke(
            case,
            MODEL,
            InvokeContext(harness_config={**ADAPTED, "allow_case_request_overrides": True}),
        )

    assert exc.value.kind == "config"
    assert "exceeds" in str(exc.value)


async def test_real_http_path_collects_streamed_text_and_metadata(monkeypatch):
    seen = {}

    def handler(request):
        seen["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            text=(
                'data: {"choices":[{"delta":{"content":"safe "}}]}\n\n'
                'data: {"choices":[{"delta":{"content":"answer"}}],'
                '"usage":{"prompt_tokens":3,"completion_tokens":2}}\n\n'
                "data: [DONE]\n\n"
            ),
            headers={"content-type": "text/event-stream"},
        )

    use_transport(monkeypatch, handler)
    import gaugix.harness.direct as direct

    def record_cost(response, *_args):
        seen["cost_model"] = response.get("model")
        return None

    monkeypatch.setattr(direct, "resolve_cost", record_cost)
    case = CASE.model_copy(
        update={
            "input": [
                Message(role=Role.system, content='@gaugix {"stream": true}'),
                Message(role=Role.user, content="hello"),
            ]
        }
    )
    config = {**ADAPTED, "allow_case_request_overrides": True}

    result = await DirectHarness().invoke(case, MODEL, InvokeContext(harness_config=config))
    output = json.loads(result.output_text)

    assert output["completion"] == "safe answer"
    assert output["stream"]["chunks"] == 2
    assert output["stream"]["interrupted"] is False
    assert result.usage.prompt_tokens == 3
    assert result.usage.completion_tokens == 2
    assert seen["payload"]["stream_options"] == {"include_usage": True}
    assert seen["cost_model"] == "openrouter/qwen/qwen3.6-27b"


async def test_stream_request_accepts_a_non_streaming_json_completion(monkeypatch):
    calls = 0

    def handler(_request):
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={
                "model": "qwen/qwen3.6-27b",
                "choices": [{"message": {"content": "ordinary JSON response"}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 3},
            },
        )

    use_transport(monkeypatch, handler)
    case = CASE.model_copy(
        update={
            "input": [
                Message(role=Role.system, content='@gaugix {"stream": true}'),
                Message(role=Role.user, content="hello"),
            ]
        }
    )

    result = await DirectHarness().invoke(
        case,
        MODEL,
        InvokeContext(harness_config={**ADAPTED, "allow_case_request_overrides": True}),
    )
    output = json.loads(result.output_text)

    assert calls == 1
    assert output["verdict"] == "allowed"
    assert output["completion"] == "ordinary JSON response"
    assert output["stream"] is None
    assert result.usage.prompt_tokens == 3
    assert result.usage.completion_tokens == 3


async def test_stream_request_preserves_a_json_guardrail_error(monkeypatch):
    def handler(_request):
        return httpx.Response(
            200,
            json={
                "error": {
                    "code": "guardrails_blocked",
                    "message": "blocked before SSE",
                    "param": {"rule_id": "kw-deny", "method": "keyword"},
                }
            },
        )

    use_transport(monkeypatch, handler)
    case = CASE.model_copy(
        update={
            "input": [
                Message(role=Role.system, content='@gaugix {"stream": true}'),
                Message(role=Role.user, content="hello"),
            ]
        }
    )

    result = await DirectHarness().invoke(
        case,
        MODEL,
        InvokeContext(harness_config={**ADAPTED, "allow_case_request_overrides": True}),
    )
    output = json.loads(result.output_text)

    assert output["verdict"] == "blocked"
    assert output["rule_id"] == "kw-deny"
    assert result.raw["captured_stream_error"]["error"]["code"] == "guardrails_blocked"
    assert result.usage.cost_usd == 0.0


async def test_stream_request_classifies_a_json_string_error_as_retryable(monkeypatch):
    def handler(_request):
        return httpx.Response(200, json={"error": "rate limited, please retry"})

    use_transport(monkeypatch, handler)
    case = CASE.model_copy(
        update={
            "input": [
                Message(role=Role.system, content='@gaugix {"stream": true}'),
                Message(role=Role.user, content="hello"),
            ]
        }
    )

    with pytest.raises(HarnessError) as exc:
        await DirectHarness().invoke(
            case,
            MODEL,
            InvokeContext(harness_config={**ADAPTED, "allow_case_request_overrides": True}),
        )

    assert exc.value.kind == "provider_error"
    assert exc.value.retryable is True
    assert "rate limited, please retry" in str(exc.value)


async def test_stream_request_rejects_a_non_json_200_without_retry(monkeypatch):
    leaked = "sk-or-v1-" + ("a" * 32)
    proxy_page = "<html>upstream proxy page</html>" + ("x" * 459) + " " + leaked

    def handler(_request):
        return httpx.Response(
            200,
            text=proxy_page,
            headers={"content-type": "text/html; charset=utf-8"},
        )

    use_transport(monkeypatch, handler)
    case = CASE.model_copy(
        update={
            "input": [
                Message(role=Role.system, content='@gaugix {"stream": true}'),
                Message(role=Role.user, content="hello"),
            ]
        }
    )

    with pytest.raises(HarnessError) as exc:
        await DirectHarness().invoke(
            case,
            MODEL,
            InvokeContext(harness_config={**ADAPTED, "allow_case_request_overrides": True}),
        )

    assert exc.value.kind == "provider_error"
    assert exc.value.retryable is False
    assert "content-type=text/html" in str(exc.value)
    assert "upstream proxy page" in str(exc.value)
    assert leaked not in str(exc.value)
    assert "sk-or-v1" not in str(exc.value)


async def test_openai_compatible_fallback_ignores_a_whitespace_key(monkeypatch):
    seen = {}

    def handler(request):
        seen["authorization"] = request.headers.get("authorization")
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "safe"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    use_transport(monkeypatch, handler)
    monkeypatch.setenv("OPENAI_API_KEY", "   ")
    model = MODEL.model_copy(update={"api_key_env": None})

    await DirectHarness().invoke(model=model, case=CASE, ctx=InvokeContext(harness_config=CAPTURE))

    assert seen["authorization"] is None


async def test_stream_tool_fragments_without_indices_continue_the_current_call(monkeypatch):
    def handler(_request):
        return httpx.Response(
            200,
            text=(
                'data: {"choices":[{"delta":{"tool_calls":[{"id":"call-1",'
                '"function":{"name":"echo_args","arguments":"{\\"a\\":"}}]}}]}\n\n'
                'data: {"choices":[{"delta":{"tool_calls":[{"function":'
                '{"arguments":"1}"}}]}}]}\n\n'
                "data: [DONE]\n\n"
            ),
            headers={"content-type": "text/event-stream"},
        )

    use_transport(monkeypatch, handler)
    case = CASE.model_copy(
        update={
            "input": [
                Message(role=Role.system, content='@gaugix {"stream": true}'),
                Message(role=Role.user, content="hello"),
            ]
        }
    )

    result = await DirectHarness().invoke(
        case,
        MODEL,
        InvokeContext(harness_config={**ADAPTED, "allow_case_request_overrides": True}),
    )
    output = json.loads(result.output_text)

    assert output["tool_calls"] == [
        {
            "id": "call-1",
            "name": "echo_args",
            "arguments": '{"a":1}',
        }
    ]


async def test_real_http_path_marks_missing_stream_usage_as_unknown_cost(monkeypatch):
    def handler(_request):
        return httpx.Response(
            200,
            text=('data: {"choices":[{"delta":{"content":"safe"}}]}\n\ndata: [DONE]\n\n'),
            headers={"content-type": "text/event-stream"},
        )

    use_transport(monkeypatch, handler)
    case = CASE.model_copy(
        update={
            "input": [
                Message(role=Role.system, content='@gaugix {"stream": true}'),
                Message(role=Role.user, content="hello"),
            ]
        }
    )
    priced = MODEL.model_copy(update={"pricing": Pricing(input_per_1m=1.0, output_per_1m=2.0)})

    result = await DirectHarness().invoke(
        case,
        priced,
        InvokeContext(
            harness_config={
                "allow_case_request_overrides": True,
                "output_adapter": "guardrail_verdict_v1",
            }
        ),
    )

    assert result.usage.prompt_tokens == 0
    assert result.usage.completion_tokens == 0
    assert result.usage.cost_usd is None


@pytest.mark.parametrize(
    "event",
    [
        'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n',
        'data: {"error":"timeout while reading upstream"}\n\n',
    ],
)
async def test_real_http_path_treats_truncated_or_string_error_stream_as_retryable(
    monkeypatch,
    event,
):
    def handler(_request):
        return httpx.Response(
            200,
            text=event,
            headers={"content-type": "text/event-stream"},
        )

    use_transport(monkeypatch, handler)
    case = CASE.model_copy(
        update={
            "input": [
                Message(role=Role.system, content='@gaugix {"stream": true}'),
                Message(role=Role.user, content="hello"),
            ]
        }
    )

    with pytest.raises(HarnessError) as exc:
        await DirectHarness().invoke(
            case,
            MODEL,
            InvokeContext(harness_config={**ADAPTED, "allow_case_request_overrides": True}),
        )

    assert exc.value.kind == "provider_error"
    assert exc.value.retryable is True


async def test_real_http_path_scores_a_midstream_guardrail_refusal(monkeypatch):
    def handler(_request):
        return httpx.Response(
            200,
            text=(
                'data: {"choices":[{"delta":{"content":"prefix"}}]}\n\n'
                'data: {"error":{"code":"guardrails_blocked","message":"blocked",'
                '"param":{"rule_id":"kw-deny","method":"keyword"}}}\n\n'
            ),
            headers={"content-type": "text/event-stream"},
        )

    use_transport(monkeypatch, handler)
    case = CASE.model_copy(
        update={
            "input": [
                Message(role=Role.system, content='@gaugix {"stream": true}'),
                Message(role=Role.user, content="hello"),
            ]
        }
    )
    config = {**ADAPTED, "allow_case_request_overrides": True}

    result = await DirectHarness().invoke(case, MODEL, InvokeContext(harness_config=config))
    output = json.loads(result.output_text)

    assert output["verdict"] == "blocked"
    assert output["rule_id"] == "kw-deny"
    assert output["completion"] == "prefix"
    assert output["stream"]["interrupted"] is True
    assert result.raw["captured_stream_error"]["error"]["code"] == "guardrails_blocked"
    assert result.usage.cost_usd is None


async def test_real_http_path_scores_a_pre_stream_http_guardrail_refusal(monkeypatch):
    body = {
        "status_code": 403,
        "type": "guardrails_violation",
        "error": {
            "code": "guardrails_blocked",
            "message": "blocked before streaming",
            "param": {"rule_id": "kw-deny", "method": "keyword"},
        },
    }

    def handler(_request):
        return httpx.Response(403, json=body)

    use_transport(monkeypatch, handler)
    case = CASE.model_copy(
        update={
            "input": [
                Message(role=Role.system, content='@gaugix {"stream": true}'),
                Message(role=Role.user, content="hello"),
            ]
        }
    )

    result = await DirectHarness().invoke(
        case,
        MODEL,
        InvokeContext(harness_config={**ADAPTED, "allow_case_request_overrides": True}),
    )
    output = json.loads(result.output_text)

    assert output["verdict"] == "blocked"
    assert output["http_status"] == 403
    assert output["rule_id"] == "kw-deny"
    assert result.raw["captured_http_error"]["body"] == body


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


async def test_direct_harness_freezes_credentials_only_when_opted_in(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    monkeypatch.setenv("GAUGIX_FREEZE_CREDENTIALS", "1")
    monkeypatch.setenv("MT0_EVAL_VK", "deployment-key")
    reset_settings_cache()
    try:
        harness = DirectHarness()
        use_transport(monkeypatch, handler)
        model = MODEL.model_copy(update={"api_key_env": "MT0_EVAL_VK"})
        config = {**CAPTURE, "request_headers_from_env": {"x-mt-vk": "MT0_EVAL_VK"}}

        await harness.invoke(CASE, model, InvokeContext(harness_config=config))
        monkeypatch.setenv("MT0_EVAL_VK", "unrelated-local-stack-key")
        await harness.invoke(CASE, model, InvokeContext(harness_config=config))

        assert len(seen) == 2
        assert all(r.headers["authorization"] == "Bearer deployment-key" for r in seen)
        assert all(r.headers["x-mt-vk"] == "deployment-key" for r in seen)
    finally:
        reset_settings_cache()


async def test_direct_harness_uses_rotated_credentials_when_freezing_is_off(monkeypatch):
    seen = {}

    def handler(request):
        seen["request"] = request
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    monkeypatch.delenv("GAUGIX_FREEZE_CREDENTIALS", raising=False)
    monkeypatch.setenv("MT0_EVAL_VK", "old-key")
    reset_settings_cache()
    harness = DirectHarness()
    monkeypatch.setenv("MT0_EVAL_VK", "rotated-key")
    use_transport(monkeypatch, handler)
    model = MODEL.model_copy(update={"api_key_env": "MT0_EVAL_VK"})
    config = {**CAPTURE, "request_headers_from_env": {"x-mt-vk": "MT0_EVAL_VK"}}

    await harness.invoke(CASE, model, InvokeContext(harness_config=config))

    assert seen["request"].headers["authorization"] == "Bearer rotated-key"
    assert seen["request"].headers["x-mt-vk"] == "rotated-key"


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
