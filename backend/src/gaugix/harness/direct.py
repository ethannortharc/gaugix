"""DirectHarness — plain chat-completion calls through litellm (ARCHITECTURE §4).

Deliberately thin. Everything provider-specific lives in two places: the model
string mapping and the cost fallback chain. If one provider misbehaves, that is a
litellm problem to route around, not a reason to grow this file.

**Cost is never fabricated.** The chain is litellm's own calculation → the user's
pricing table → `None`. A `None` renders as "n/a" in the UI; a fabricated 0 would
silently corrupt a cost-per-quality comparison.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import time
from collections.abc import Mapping
from typing import Any, cast

import httpx

from gaugix.config import credential_environment, redact_for_display
from gaugix.domain import (
    CaseSnapshot,
    HarnessError,
    HarnessKind,
    InvocationResult,
    InvokeContext,
    ModelSnapshot,
    Pricing,
    Provider,
    Usage,
)
from gaugix.logging_setup import get_logger

log = get_logger("gaugix.harness.direct")

#: Provider errors worth retrying (ARCHITECTURE §5). Matched against the exception
#: class name and message, because litellm's exception hierarchy varies by provider.
RETRYABLE_MARKERS = (
    "ratelimit",
    "rate_limit",
    "rate limit",
    "timeout",
    "timedout",
    "serviceunavailable",
    "internalserver",
    "apiconnection",
    "overloaded",
    "502",
    "503",
    "504",
    "529",
)

_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_HEADER_NAME = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
_FUNCTION_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_CASE_DIRECTIVE = re.compile(r"^\s*@gaugix\s+(\{.*\})\s*$", re.DOTALL)
_FINGERPRINT_KEY = secrets.token_bytes(32)
GUARDRAIL_VERDICT_V1 = "guardrail_verdict_v1"
DEFAULT_TIMEOUT_S = 600.0
MAX_CASE_OVERRIDE_BYTES = 32_768


def litellm_model_string(model: ModelSnapshot) -> str:
    """Map a Gaugix model profile onto litellm's `provider/model` convention."""
    provider = Provider(model.provider)
    if provider is Provider.anthropic:
        return f"anthropic/{model.model_id}"
    if provider is Provider.gemini:
        return f"gemini/{model.model_id}"
    if provider is Provider.openai:
        return model.model_id
    if provider is Provider.openai_compatible:
        # litellm routes any OpenAI-shaped endpoint through the openai/ prefix.
        return (
            model.model_id if model.model_id.startswith("openai/") else f"openai/{model.model_id}"
        )
    raise HarnessError(
        f"provider {model.provider!r} cannot be called directly", retryable=False, kind="config"
    )


def is_retryable(exc: BaseException) -> bool:
    """Whether a provider exception looks transient."""
    response = getattr(exc, "response", None)
    status = getattr(exc, "status_code", None)
    if not isinstance(status, int) and response is not None:
        status = getattr(response, "status_code", None)
    if status in {429, 500, 502, 503, 504, 529}:
        return True
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)):
        return True
    haystack = f"{type(exc).__name__} {exc}".lower()
    return any(marker in haystack for marker in RETRYABLE_MARKERS)


def cost_from_pricing(pricing: Pricing | None, usage: Usage) -> float | None:
    """Compute cost from a per-1M-token pricing override."""
    if pricing is None:
        return None
    return (
        usage.prompt_tokens * pricing.input_per_1m + usage.completion_tokens * pricing.output_per_1m
    ) / 1_000_000


def resolve_cost(
    response: Any, model: ModelSnapshot, usage: Usage, pricing_table: dict[str, Pricing] | None
) -> float | None:
    """litellm's cost → the model's own override → the settings pricing table → None."""
    try:
        import litellm

        computed = litellm.completion_cost(completion_response=response)
        if computed is not None and computed > 0:
            return float(computed)
    except Exception:
        pass

    from_model = cost_from_pricing(model.pricing, usage)
    if from_model is not None:
        return from_model

    if pricing_table:
        entry = pricing_table.get(model.model_id) or pricing_table.get(model.name)
        if entry is not None:
            return cost_from_pricing(entry, usage)

    # Unknown is unknown. The UI shows "n/a"; it must never show a made-up 0.
    return None


def _secret_fingerprint(value: str | None) -> str:
    """Return a process-local correlation id without enabling offline key guesses."""
    if not value:
        return "absent"
    return hashlib.blake2b(value.encode(), key=_FINGERPRINT_KEY, digest_size=6).hexdigest()


class DirectHarness:
    """Calls the provider's chat-completion API through litellm."""

    kind = str(HarnessKind.direct)

    def __init__(self, pricing_table: dict[str, Pricing] | None = None) -> None:
        self.pricing_table = pricing_table or {}

    async def invoke(
        self, case: CaseSnapshot, model: ModelSnapshot, ctx: InvokeContext
    ) -> InvocationResult:
        # Keep one request internally consistent even if a development process
        # rotates its environment concurrently. Production can opt into a
        # process-wide immutable snapshot through GAUGIX_FREEZE_CREDENTIALS.
        credential_env = dict(credential_environment())
        credential_before_import = _secret_fingerprint(credential_env.get(model.api_key_env or ""))
        import litellm

        credential_after_import = _secret_fingerprint(os.environ.get(model.api_key_env or ""))

        model_string = litellm_model_string(model)
        messages, case_params = case_request_overrides(case.messages_for_api(), ctx.harness_config)
        if (
            _capture_policy(ctx.harness_config) is not None
            and Provider(model.provider) is not Provider.openai_compatible
        ):
            raise HarnessError(
                "capture_http_errors requires an openai_compatible model profile",
                retryable=False,
                kind="config",
            )
        params: dict[str, Any] = {
            **model.params,
            **(ctx.params or {}),
            **case_params,
        }
        provider = Provider(model.provider)
        stream_requested = params.get("stream") is True
        if stream_requested and provider is not Provider.openai_compatible:
            raise HarnessError(
                "streaming (stream=true) currently requires an OpenAI-compatible model profile",
                retryable=False,
                kind="config",
            )
        env_headers = headers_from_env(ctx.harness_config, environment=credential_env)

        kwargs: dict[str, Any] = {"model": model_string, "messages": messages, **params}
        if env_headers:
            configured_headers = kwargs.get("extra_headers") or {}
            if not isinstance(configured_headers, Mapping):
                raise HarnessError(
                    "direct model extra_headers must be an object",
                    retryable=False,
                    kind="config",
                )
            kwargs["extra_headers"] = _merge_headers(configured_headers, env_headers)
        if model.base_url:
            kwargs["base_url"] = model.base_url
        # litellm will not pick a key up from an arbitrary env var name, so pass it.
        api_key = (credential_env.get(model.api_key_env or "") or "").strip() or None
        if not api_key and Provider(model.provider) is Provider.openai_compatible:
            # Match LiteLLM's OpenAI-compatible fallback when a profile does not
            # name a custom key variable. Adding error capture must not silently
            # turn a previously authenticated executor into an anonymous one.
            api_key = (credential_env.get("OPENAI_API_KEY") or "").strip() or None
        if api_key:
            kwargs["api_key"] = api_key
        timeout_s = ctx.timeout_s if ctx.timeout_s and ctx.timeout_s > 0 else DEFAULT_TIMEOUT_S
        kwargs["timeout"] = timeout_s

        started = time.perf_counter()
        try:
            if provider is Provider.openai_compatible and (
                _capture_policy(ctx.harness_config) is not None or stream_requested
            ):
                response = await _openai_compatible_completion(
                    model=model,
                    messages=messages,
                    params=params,
                    env_headers=env_headers,
                    api_key=api_key,
                    timeout_s=timeout_s,
                )
            else:
                response = await litellm.acompletion(**kwargs)
        except HarnessError:
            raise
        except Exception as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            captured = capture_http_error(
                exc,
                config=ctx.harness_config,
                messages=messages,
                model_string=model_string,
                provider=str(model.provider),
                latency_ms=latency_ms,
            )
            if captured is not None:
                return captured
            status, _ = _http_error_details(exc)
            if status in {401, 403}:
                log.warning(
                    "direct_auth_rejected",
                    status=status,
                    api_key_env=model.api_key_env,
                    credential_before_import=credential_before_import,
                    credential_after_import=credential_after_import,
                    api_key=_secret_fingerprint(api_key),
                    request_headers={
                        name: _secret_fingerprint(value) for name, value in env_headers.items()
                    },
                )
            auth_diagnostic = ""
            if status == 401:
                auth_diagnostic = (
                    " [credential diagnostics: "
                    f"env={model.api_key_env or 'unset'}, "
                    f"before={credential_before_import}, "
                    f"after={credential_after_import}, "
                    f"request={_secret_fingerprint(api_key)}, "
                    "headers="
                    + ",".join(
                        f"{name}:{_secret_fingerprint(value)}"
                        for name, value in sorted(env_headers.items())
                    )
                    + "]"
                )
            raise HarnessError(
                f"{type(exc).__name__}: {exc}{auth_diagnostic}",
                retryable=is_retryable(exc),
                kind="provider_error",
            ) from exc
        latency_ms = int((time.perf_counter() - started) * 1000)

        stream_info = _stream_info(response)
        stream_error = _stream_error(response)
        output_text, usage = _extract(response, latency_ms)
        stream_usage_missing = (
            stream_info is not None
            and isinstance(response, Mapping)
            and (not isinstance(response.get("usage"), Mapping) or not response.get("usage"))
        )
        usage.cost_usd = (
            None
            if stream_usage_missing
            else resolve_cost(response, model, usage, self.pricing_table)
        )
        source_output = output_text
        tool_calls = _extract_tool_calls(response)
        if stream_error is not None:
            code = _error_code(stream_error)
            policy = _capture_policy(ctx.harness_config)
            if policy is None or code not in policy[1]:
                raise HarnessError(
                    f"stream ended with an uncaptured error: {redact_for_display(stream_error)}",
                    retryable=_retryable_stream_error(stream_error),
                    kind="provider_error",
                )
            # A captured refusal before the first SSE chunk never reached the
            # billable upstream generation. Mid-stream failures retain unknown
            # cost because some provider work has already happened.
            if stream_info is not None and stream_info.get("chunks") == 0:
                usage.cost_usd = 0.0
            adapted = _output_adapter(ctx.harness_config) == GUARDRAIL_VERDICT_V1
            output = (
                guardrail_verdict_v1(
                    completion=source_output,
                    error_body=stream_error,
                    http_status=200,
                    stream=stream_info,
                    tool_calls=tool_calls,
                )
                if adapted
                else stream_error
            )
            output_text = json.dumps(output, ensure_ascii=False, sort_keys=True)
            return InvocationResult(
                output_text=output_text,
                messages=[*messages, {"role": "assistant", "content": source_output}],
                usage=usage,
                raw={
                    "model": model_string,
                    "provider": str(model.provider),
                    "captured_stream_error": stream_error,
                    "source_output_text": source_output,
                    "stream": stream_info,
                    **({"tool_calls": tool_calls} if tool_calls else {}),
                },
            )
        if _output_adapter(ctx.harness_config) == GUARDRAIL_VERDICT_V1:
            output_text = json.dumps(
                guardrail_verdict_v1(
                    completion=source_output,
                    stream=stream_info,
                    tool_calls=tool_calls,
                ),
                ensure_ascii=False,
                sort_keys=True,
            )

        return InvocationResult(
            output_text=output_text,
            messages=[*messages, {"role": "assistant", "content": source_output}],
            usage=usage,
            raw={
                "model": model_string,
                "provider": str(model.provider),
                **(
                    {"source_output_text": source_output}
                    if _output_adapter(ctx.harness_config) == GUARDRAIL_VERDICT_V1
                    else {}
                ),
                **({"stream": stream_info} if stream_info is not None else {}),
                **({"tool_calls": tool_calls} if tool_calls else {}),
            },
        )


async def _openai_compatible_completion(
    *,
    model: ModelSnapshot,
    messages: list[dict[str, str]],
    params: Mapping[str, Any],
    env_headers: Mapping[str, str],
    api_key: str | None,
    timeout_s: float | None,
) -> dict[str, Any]:
    """Call a policy gateway without letting an adapter discard its error body.

    LiteLLM's generic ``APIError`` keeps the status but intentionally constructs
    the exception with ``body=None``. That is fine for normal inference failures,
    but a scorer cannot distinguish a structured policy refusal from an unrelated
    403 after the body has gone. This narrow path is used only by an explicitly
    configured OpenAI-compatible harness; all normal Direct calls still use
    LiteLLM's provider routing.
    """
    if not model.base_url:
        raise HarnessError(
            "direct OpenAI-compatible streaming/error capture requires a base_url",
            retryable=False,
            kind="config",
        )
    payload: dict[str, Any] = {
        "model": model.model_id.removeprefix("openai/"),
        "messages": messages,
        **params,
    }
    if payload.get("stream") is True:
        payload.setdefault("stream_options", {"include_usage": True})
    configured_headers = payload.pop("extra_headers", {}) or {}
    if not isinstance(configured_headers, Mapping):
        raise HarnessError(
            "direct model extra_headers must be an object",
            retryable=False,
            kind="config",
        )
    headers = {"content-type": "application/json"}
    if api_key:
        headers["authorization"] = f"Bearer {api_key}"
    headers.update(_merge_headers(configured_headers, env_headers))
    timeout = timeout_s if timeout_s and timeout_s > 0 else DEFAULT_TIMEOUT_S
    async with httpx.AsyncClient(timeout=timeout) as client:
        if payload.get("stream") is True:
            body = await _read_openai_stream(
                client,
                model.base_url.rstrip("/") + "/chat/completions",
                headers,
                payload,
            )
        else:
            response = await client.post(
                model.base_url.rstrip("/") + "/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            body = response.json()
    if not isinstance(body, dict):
        raise HarnessError(
            "OpenAI-compatible endpoint returned a non-object JSON response",
            retryable=False,
            kind="provider_error",
        )
    return {str(key): value for key, value in body.items()}


async def _read_openai_stream(
    client: httpx.AsyncClient,
    url: str,
    headers: Mapping[str, str],
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Collect exactly what an OpenAI-compatible SSE client receives."""
    started = time.perf_counter()
    parts: list[str] = []
    chunks = 0
    first_delta_ms: int | None = None
    interrupted = False
    error: dict[str, Any] | None = None
    saw_done = False
    usage: dict[str, Any] = {}
    tool_calls: dict[int, dict[str, Any]] = {}

    async with client.stream("POST", url, headers=headers, json=dict(payload)) as response:
        if response.is_error:
            await response.aread()
            response.raise_for_status()
        media_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if media_type != "text/event-stream":
            await response.aread()
            try:
                body = response.json()
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                excerpt = str(redact_for_display(response.text))[:500]
                raise HarnessError(
                    "streaming endpoint returned a non-SSE, non-JSON 200 response "
                    f"(content-type={media_type or 'missing'}): {excerpt}",
                    retryable=False,
                    kind="provider_error",
                ) from exc
            if not isinstance(body, dict):
                raise HarnessError(
                    "streaming endpoint returned a non-object JSON response "
                    f"(content-type={media_type or 'missing'})",
                    retryable=False,
                    kind="provider_error",
                )
            normalized = {str(key): value for key, value in body.items()}
            raw_error = normalized.get("error")
            if raw_error is not None:
                normalized["_gaugix_stream"] = {
                    "chunks": 0,
                    "first_delta_ms": None,
                    "interrupted": True,
                }
                normalized["_gaugix_stream_error"] = (
                    {
                        key: value
                        for key, value in normalized.items()
                        if not key.startswith("_gaugix_")
                    }
                    if isinstance(raw_error, Mapping)
                    else {
                        "error": {
                            "code": "stream_error",
                            "message": str(raw_error),
                        }
                    }
                )
            return normalized
        async for line in response.aiter_lines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                saw_done = True
                break
            try:
                event = json.loads(data)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, Mapping):
                continue
            if isinstance(event.get("usage"), Mapping):
                usage = {str(key): value for key, value in event["usage"].items()}
            raw_error = event.get("error")
            if raw_error is not None:
                error = (
                    {str(key): value for key, value in event.items()}
                    if isinstance(raw_error, Mapping)
                    else {
                        "error": {
                            "code": "stream_error",
                            "message": str(raw_error),
                        }
                    }
                )
                interrupted = True
                break
            for choice in event.get("choices") or []:
                if not isinstance(choice, Mapping):
                    continue
                delta = choice.get("delta")
                if not isinstance(delta, Mapping):
                    continue
                piece = delta.get("content")
                if isinstance(piece, str) and piece:
                    if first_delta_ms is None:
                        first_delta_ms = int((time.perf_counter() - started) * 1000)
                    parts.append(piece)
                    chunks += 1
                for raw_call in delta.get("tool_calls") or []:
                    if not isinstance(raw_call, Mapping):
                        continue
                    index = raw_call.get("index")
                    if isinstance(index, bool) or not isinstance(index, int):
                        function = raw_call.get("function")
                        starts_call = bool(raw_call.get("id")) or (
                            isinstance(function, Mapping) and bool(function.get("name"))
                        )
                        if tool_calls and not starts_call:
                            index = max(tool_calls)
                        else:
                            index = max(tool_calls, default=-1) + 1
                    call = tool_calls.setdefault(
                        index,
                        {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
                    )
                    if isinstance(raw_call.get("id"), str):
                        call["id"] += raw_call["id"]
                    function = raw_call.get("function")
                    if isinstance(function, Mapping):
                        if isinstance(function.get("name"), str):
                            call["function"]["name"] += function["name"]
                        if isinstance(function.get("arguments"), str):
                            call["function"]["arguments"] += function["arguments"]

    if error is None and not saw_done:
        error = {
            "error": {
                "code": "stream_interrupted",
                "message": "stream ended before [DONE]",
            }
        }
        interrupted = True

    return {
        "model": payload.get("model"),
        "choices": [
            {
                "message": {
                    "content": "".join(parts),
                    "tool_calls": [tool_calls[key] for key in sorted(tool_calls)],
                }
            }
        ],
        "usage": usage,
        "_gaugix_stream": {
            "chunks": chunks,
            "first_delta_ms": first_delta_ms,
            "interrupted": interrupted,
        },
        "_gaugix_stream_error": error,
    }


def _merge_headers(*sources: Mapping[str, Any]) -> dict[str, str]:
    """Merge HTTP headers case-insensitively, with later sources taking precedence."""
    headers: dict[str, str] = {}
    for source in sources:
        headers.update({str(key).lower(): str(value) for key, value in source.items()})
    return headers


def capture_http_error(
    exc: BaseException,
    *,
    config: Mapping[str, Any],
    messages: list[dict[str, str]],
    model_string: str,
    provider: str,
    latency_ms: int,
) -> InvocationResult | None:
    """Return an invocation result for one explicitly allowed structured HTTP error.

    Direct model calls normally treat every non-2xx response as an execution error.
    Some APIs use a structured HTTP refusal as the *successful outcome under test*
    (for example an AI gateway returning ``403/error.code=guardrails_blocked``).
    A harness profile may opt into capturing exact status/code pairs so scorers can
    inspect the original response body. Everything else remains a provider error.
    """
    policy = _capture_policy(config)
    if policy is None:
        return None
    statuses, codes = policy
    status, body = _http_error_details(exc)
    if status not in statuses or not isinstance(body, dict):
        return None
    code = _error_code(body)
    if code not in codes:
        return None

    adapted = _output_adapter(config) == GUARDRAIL_VERDICT_V1
    output = guardrail_verdict_v1(error_body=body, http_status=status) if adapted else body
    output_text = json.dumps(output, ensure_ascii=False, sort_keys=True)
    return InvocationResult(
        output_text=output_text,
        messages=[*messages, {"role": "assistant", "content": output_text}],
        # The Gateway rejected the request before upstream generation, so the
        # model-token cost for this captured outcome is exactly zero.
        usage=Usage(latency_ms=latency_ms, cost_usd=0.0),
        raw={
            "model": model_string,
            "provider": provider,
            "captured_http_error": {
                "status_code": status,
                "error_code": code,
                "body": body,
            },
        },
    )


def validate_direct_harness_config(config: Mapping[str, Any]) -> None:
    """Validate Direct Harness options without resolving environment secrets."""
    _capture_policy(config)
    _header_env_names(config)
    _output_adapter(config)
    _case_request_overrides_enabled(config)


def guardrail_verdict_v1(
    *,
    completion: str = "",
    error_body: Mapping[str, Any] | None = None,
    http_status: int | None = None,
    stream: Mapping[str, Any] | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Normalize a Gateway result to the guardrail probe's stable v1 contract.

    The transport response remains available in ``InvocationResult.raw``.  The
    scorer-facing output is intentionally flat so CLI and direct executors can
    run the same Guardrail test sets without teaching every set about HTTP error
    envelopes or provider-specific success bodies.
    """
    verdict: dict[str, Any] = {
        "schema_version": "guardrail-verdict/v1",
        "verdict": "allowed",
        "action": "allow",
        "http_status": 200 if http_status is None else http_status,
        "error_code": None,
        "error_type": None,
        "rule_id": None,
        "method": None,
        "category": None,
        "rule_category": None,
        "guard_provider": None,
        "refusal": None,
        "completion": completion,
        "tool_calls": tool_calls or [],
        "stream": dict(stream) if stream is not None else None,
    }
    if error_body is None:
        return verdict

    error = error_body.get("error")
    error = error if isinstance(error, Mapping) else {}
    param = error.get("param")
    param = param if isinstance(param, Mapping) else {}
    code = error.get("code")
    status = http_status
    if status is None:
        candidate = error_body.get("status_code")
        status = candidate if isinstance(candidate, int) and not isinstance(candidate, bool) else 0
    verdict.update(
        {
            "http_status": status,
            "error_code": code if isinstance(code, str) else None,
            "error_type": (
                error_body.get("type")
                if isinstance(error_body.get("type"), str)
                else error.get("type")
                if isinstance(error.get("type"), str)
                else None
            ),
            "refusal": error.get("message") if isinstance(error.get("message"), str) else None,
        }
    )
    if code == "guardrails_blocked":
        verdict.update(
            {
                "verdict": "blocked",
                "action": "block",
                "rule_id": param.get("rule_id"),
                "method": param.get("method") or param.get("check"),
                "category": param.get("category"),
                "rule_category": param.get("rule_category"),
                "guard_provider": param.get("provider"),
            }
        )
    else:
        verdict.update({"verdict": "probe_error", "action": "error"})
    return verdict


def case_request_overrides(
    messages: list[dict[str, str]], config: Mapping[str, Any]
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Consume a narrowly scoped first-message directive for Direct API tests.

    Cases may select streaming, a token budget, strict structured output and
    declared function tools.  They cannot select a URL, credential, request
    header or arbitrary LiteLLM parameter.  The structured options are needed
    by real-model Guardrail tests: a JSON-Schema ``const`` makes output-side
    test payloads reproducible, while a forced function schema exercises the
    real MCP boundary without replacing the business LLM with a stub.
    """
    if not messages:
        return messages, {}
    first = messages[0]
    if first.get("role") != "system":
        return messages, {}
    match = _CASE_DIRECTIVE.fullmatch(first.get("content") or "")
    if not match:
        return messages, {}
    if not _case_request_overrides_enabled(config):
        raise HarnessError(
            "@gaugix case request directive requires allow_case_request_overrides=true",
            retryable=False,
            kind="config",
        )
    if len(match.group(1).encode("utf-8")) > MAX_CASE_OVERRIDE_BYTES:
        raise HarnessError(
            f"@gaugix case request directive exceeds {MAX_CASE_OVERRIDE_BYTES} bytes",
            retryable=False,
            kind="config",
        )
    try:
        raw = json.loads(match.group(1))
    except (json.JSONDecodeError, RecursionError) as exc:
        raise HarnessError(
            f"invalid @gaugix case request directive: {exc}",
            retryable=False,
            kind="config",
        ) from exc
    if not isinstance(raw, Mapping):
        raise HarnessError(
            "@gaugix case request directive must be an object",
            retryable=False,
            kind="config",
        )
    unknown = set(raw) - {
        "stream",
        "max_tokens",
        "response_format",
        "tools",
        "tool_choice",
    }
    if unknown:
        raise HarnessError(
            "@gaugix case request directive has unsupported keys: "
            + ", ".join(sorted(str(key) for key in unknown)),
            retryable=False,
            kind="config",
        )
    overrides: dict[str, Any] = {}
    if "stream" in raw:
        if not isinstance(raw["stream"], bool):
            raise HarnessError("@gaugix stream must be a boolean", retryable=False, kind="config")
        overrides["stream"] = raw["stream"]
    if "max_tokens" in raw:
        value = raw["max_tokens"]
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 4096:
            raise HarnessError(
                "@gaugix max_tokens must be an integer from 1 to 4096",
                retryable=False,
                kind="config",
            )
        overrides["max_tokens"] = value
    if "response_format" in raw:
        overrides["response_format"] = _validate_case_response_format(raw["response_format"])
    tool_names: frozenset[str] = frozenset()
    if "tools" in raw:
        tools, tool_names = _validate_case_tools(raw["tools"])
        overrides["tools"] = tools
    if "tool_choice" in raw:
        # ``none`` is also useful when an OpenAI-compatible Gateway adds
        # server-side MCP tools. It disables those tools for a non-tool case
        # without letting the case select an arbitrary external capability.
        if "tools" not in raw and raw["tool_choice"] != "none":
            raise HarnessError(
                "@gaugix tool_choice requires tools in the same directive unless it is none",
                retryable=False,
                kind="config",
            )
        overrides["tool_choice"] = _validate_case_tool_choice(raw["tool_choice"], tool_names)
    return messages[1:], overrides


def _validate_case_response_format(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {"type", "json_schema"}:
        raise HarnessError(
            "@gaugix response_format must be a strict json_schema object",
            retryable=False,
            kind="config",
        )
    spec = value.get("json_schema")
    if value.get("type") != "json_schema" or not isinstance(spec, Mapping):
        raise HarnessError(
            "@gaugix response_format must use type=json_schema",
            retryable=False,
            kind="config",
        )
    name = spec.get("name")
    schema = spec.get("schema")
    if (
        not isinstance(name, str)
        or not _FUNCTION_NAME.fullmatch(name)
        or spec.get("strict") is not True
        or not isinstance(schema, Mapping)
        or set(spec) != {"name", "strict", "schema"}
    ):
        raise HarnessError(
            "@gaugix json_schema needs a valid name, strict=true and an object schema",
            retryable=False,
            kind="config",
        )
    return cast(dict[str, Any], json.loads(json.dumps(value)))


def _validate_case_tools(value: Any) -> tuple[list[dict[str, Any]], frozenset[str]]:
    if not isinstance(value, list) or not 1 <= len(value) <= 8:
        raise HarnessError(
            "@gaugix tools must contain between 1 and 8 function tools",
            retryable=False,
            kind="config",
        )
    result: list[dict[str, Any]] = []
    names: set[str] = set()
    for tool in value:
        if (
            not isinstance(tool, Mapping)
            or set(tool) != {"type", "function"}
            or tool.get("type") != "function"
        ):
            raise HarnessError(
                "@gaugix tools may contain only OpenAI function definitions",
                retryable=False,
                kind="config",
            )
        function = tool.get("function")
        if not isinstance(function, Mapping):
            raise HarnessError(
                "@gaugix function definition must be an object",
                retryable=False,
                kind="config",
            )
        allowed = {"name", "description", "parameters", "strict"}
        if set(function) - allowed:
            raise HarnessError(
                "@gaugix function definition has unsupported keys",
                retryable=False,
                kind="config",
            )
        name = function.get("name")
        parameters = function.get("parameters")
        if (
            not isinstance(name, str)
            or not _FUNCTION_NAME.fullmatch(name)
            or name in names
            or not isinstance(parameters, Mapping)
        ):
            raise HarnessError(
                "@gaugix functions need unique valid names and object parameters",
                retryable=False,
                kind="config",
            )
        description = function.get("description")
        if description is not None and (
            not isinstance(description, str) or len(description) > 2_000
        ):
            raise HarnessError(
                "@gaugix function description must be at most 2000 characters",
                retryable=False,
                kind="config",
            )
        if "strict" in function and not isinstance(function["strict"], bool):
            raise HarnessError(
                "@gaugix function strict must be a boolean",
                retryable=False,
                kind="config",
            )
        names.add(name)
        result.append(json.loads(json.dumps(tool)))
    return result, frozenset(names)


def _validate_case_tool_choice(value: Any, tool_names: frozenset[str]) -> Any:
    if isinstance(value, str):
        if value not in {"auto", "none", "required"}:
            raise HarnessError(
                "@gaugix string tool_choice must be auto, none or required",
                retryable=False,
                kind="config",
            )
        return value
    if (
        not isinstance(value, Mapping)
        or set(value) != {"type", "function"}
        or value.get("type") != "function"
    ):
        raise HarnessError(
            "@gaugix tool_choice must select a declared function",
            retryable=False,
            kind="config",
        )
    function = value.get("function")
    name = function.get("name") if isinstance(function, Mapping) else None
    if not isinstance(function, Mapping) or set(function) != {"name"} or name not in tool_names:
        raise HarnessError(
            "@gaugix tool_choice must name one of the directive tools",
            retryable=False,
            kind="config",
        )
    return json.loads(json.dumps(value))


def _case_request_overrides_enabled(config: Mapping[str, Any]) -> bool:
    value = config.get("allow_case_request_overrides", False)
    if not isinstance(value, bool):
        raise HarnessError(
            "direct harness allow_case_request_overrides must be a boolean",
            retryable=False,
            kind="config",
        )
    return value


def headers_from_env(
    config: Mapping[str, Any], *, environment: Mapping[str, str] | None = None
) -> dict[str, str]:
    """Resolve configured request headers while keeping their values out of profiles."""
    source = os.environ if environment is None else environment
    headers: dict[str, str] = {}
    for header, env_name in _header_env_names(config).items():
        value = source.get(env_name, "").strip()
        if not value:
            raise HarnessError(
                f"direct harness request header {header!r} needs environment variable {env_name}",
                retryable=False,
                kind="config",
            )
        headers[header] = value
    return headers


def _header_env_names(config: Mapping[str, Any]) -> dict[str, str]:
    raw = config.get("request_headers_from_env")
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise HarnessError(
            "direct harness request_headers_from_env must be an object",
            retryable=False,
            kind="config",
        )
    result: dict[str, str] = {}
    for header, env_name in raw.items():
        if not isinstance(header, str) or not _HEADER_NAME.fullmatch(header):
            raise HarnessError(
                "request_headers_from_env keys must be valid HTTP header names",
                retryable=False,
                kind="config",
            )
        if not isinstance(env_name, str) or not _ENV_NAME.fullmatch(env_name):
            raise HarnessError(
                "request_headers_from_env values must be environment variable names",
                retryable=False,
                kind="config",
            )
        result[header] = env_name
    return result


def _capture_policy(
    config: Mapping[str, Any],
) -> tuple[frozenset[int], frozenset[str]] | None:
    raw = config.get("capture_http_errors")
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise HarnessError(
            "direct harness capture_http_errors must be an object",
            retryable=False,
            kind="config",
        )
    raw_statuses = raw.get("status_codes")
    raw_codes = raw.get("error_codes")
    if (
        not isinstance(raw_statuses, list)
        or not raw_statuses
        or any(isinstance(value, bool) or not isinstance(value, int) for value in raw_statuses)
    ):
        raise HarnessError(
            "capture_http_errors.status_codes must be a non-empty integer list",
            retryable=False,
            kind="config",
        )
    if (
        not isinstance(raw_codes, list)
        or not raw_codes
        or any(not isinstance(value, str) or not value.strip() for value in raw_codes)
    ):
        raise HarnessError(
            "capture_http_errors.error_codes must be a non-empty string list",
            retryable=False,
            kind="config",
        )
    if any(value < 400 or value > 599 for value in raw_statuses):
        raise HarnessError(
            "capture_http_errors.status_codes must contain only HTTP 4xx/5xx values",
            retryable=False,
            kind="config",
        )
    return frozenset(raw_statuses), frozenset(value.strip() for value in raw_codes)


def _output_adapter(config: Mapping[str, Any]) -> str | None:
    value = config.get("output_adapter")
    if value is None:
        return None
    if value != GUARDRAIL_VERDICT_V1:
        raise HarnessError(
            f"direct harness output_adapter must be {GUARDRAIL_VERDICT_V1!r}",
            retryable=False,
            kind="config",
        )
    return GUARDRAIL_VERDICT_V1


def _http_error_details(exc: BaseException) -> tuple[int | None, dict[str, Any] | None]:
    response = getattr(exc, "response", None)
    status = getattr(exc, "status_code", None)
    if not isinstance(status, int) and response is not None:
        status = getattr(response, "status_code", None)
    if isinstance(status, bool) or not isinstance(status, int):
        status = None

    for candidate in (getattr(exc, "body", None), response):
        body = _json_body(candidate)
        if body is not None:
            return status, body
    return status, None


def _json_body(value: Any) -> dict[str, Any] | None:
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return None
        return _json_body(decoded)
    if value is None:
        return None
    json_method = getattr(value, "json", None)
    if callable(json_method):
        try:
            return _json_body(json_method())
        except (TypeError, ValueError):
            pass
    return _json_body(getattr(value, "text", None))


def _error_code(body: Mapping[str, Any]) -> str | None:
    error = body.get("error")
    if not isinstance(error, Mapping):
        return None
    code = error.get("code")
    return code if isinstance(code, str) else None


def _stream_info(response: Any) -> dict[str, Any] | None:
    if not isinstance(response, Mapping):
        return None
    value = response.get("_gaugix_stream")
    return {str(key): item for key, item in value.items()} if isinstance(value, Mapping) else None


def _stream_error(response: Any) -> dict[str, Any] | None:
    if not isinstance(response, Mapping):
        return None
    value = response.get("_gaugix_stream_error")
    return {str(key): item for key, item in value.items()} if isinstance(value, Mapping) else None


def _retryable_stream_error(body: Mapping[str, Any]) -> bool:
    """Apply the ordinary transient-error policy to an in-band SSE error."""
    code = _error_code(body)
    if code == "stream_interrupted":
        return True
    nested = body.get("error")
    status = body.get("status_code")
    if not isinstance(status, int) and isinstance(nested, Mapping):
        status = nested.get("status_code") or nested.get("status")
    if isinstance(status, int) and status in {429, 500, 502, 503, 504, 529}:
        return True
    haystack = json.dumps(body, ensure_ascii=False, default=str).lower()
    return any(marker in haystack for marker in RETRYABLE_MARKERS)


def _extract_tool_calls(response: Any) -> list[dict[str, Any]]:
    if isinstance(response, Mapping):
        choices = response.get("choices") or []
        first = choices[0] if isinstance(choices, list) and choices else {}
        message = first.get("message") if isinstance(first, Mapping) else {}
        raw_calls = message.get("tool_calls") if isinstance(message, Mapping) else []
    else:
        try:
            raw_calls = response.choices[0].message.tool_calls
        except (AttributeError, IndexError, KeyError):
            raw_calls = []
    calls: list[dict[str, Any]] = []
    for raw in raw_calls or []:
        if isinstance(raw, Mapping):
            function = raw.get("function")
            function = function if isinstance(function, Mapping) else {}
            calls.append(
                {
                    "id": raw.get("id"),
                    "name": function.get("name"),
                    "arguments": function.get("arguments"),
                }
            )
            continue
        function = getattr(raw, "function", None)
        calls.append(
            {
                "id": getattr(raw, "id", None),
                "name": getattr(function, "name", None),
                "arguments": getattr(function, "arguments", None),
            }
        )
    return calls


def _extract(response: Any, latency_ms: int) -> tuple[str, Usage]:
    """Pull text and token counts out of a litellm response, tolerating shape drift."""
    if isinstance(response, Mapping):
        choices = response.get("choices") or []
        first = choices[0] if isinstance(choices, list) and choices else {}
        message = first.get("message") if isinstance(first, Mapping) else {}
        text = str(message.get("content") or "") if isinstance(message, Mapping) else ""
        raw_usage = response.get("usage") or {}
        prompt_tokens = (
            int(raw_usage.get("prompt_tokens") or 0) if isinstance(raw_usage, Mapping) else 0
        )
        completion_tokens = (
            int(raw_usage.get("completion_tokens") or 0) if isinstance(raw_usage, Mapping) else 0
        )
        return text, Usage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
        )

    text = ""
    try:
        choice = response.choices[0]
        text = getattr(choice.message, "content", None) or ""
    except (AttributeError, IndexError, KeyError):
        text = ""

    prompt_tokens = completion_tokens = 0
    raw_usage = getattr(response, "usage", None)
    if raw_usage is not None:
        prompt_tokens = int(getattr(raw_usage, "prompt_tokens", 0) or 0)
        completion_tokens = int(getattr(raw_usage, "completion_tokens", 0) or 0)

    return text, Usage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        latency_ms=latency_ms,
    )
