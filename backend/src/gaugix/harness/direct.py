"""DirectHarness — plain chat-completion calls through litellm (ARCHITECTURE §4).

Deliberately thin. Everything provider-specific lives in two places: the model
string mapping and the cost fallback chain. If one provider misbehaves, that is a
litellm problem to route around, not a reason to grow this file.

**Cost is never fabricated.** The chain is litellm's own calculation → the user's
pricing table → `None`. A `None` renders as "n/a" in the UI; a fabricated 0 would
silently corrupt a cost-per-quality comparison.
"""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Mapping
from typing import Any

import httpx

from gaugix.config import read_api_key
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

#: Provider errors worth retrying (ARCHITECTURE §5). Matched against the exception
#: class name and message, because litellm's exception hierarchy varies by provider.
RETRYABLE_MARKERS = (
    "ratelimit",
    "rate_limit",
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
GUARDRAIL_VERDICT_V1 = "guardrail_verdict_v1"
DEFAULT_TIMEOUT_S = 600.0


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


class DirectHarness:
    """Calls the provider's chat-completion API through litellm."""

    kind = str(HarnessKind.direct)

    def __init__(self, pricing_table: dict[str, Pricing] | None = None) -> None:
        self.pricing_table = pricing_table or {}

    async def invoke(
        self, case: CaseSnapshot, model: ModelSnapshot, ctx: InvokeContext
    ) -> InvocationResult:
        import litellm

        model_string = litellm_model_string(model)
        messages = case.messages_for_api()
        params: dict[str, Any] = {**model.params, **(ctx.params or {})}
        env_headers = headers_from_env(ctx.harness_config)

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
        api_key = read_api_key(model.api_key_env)
        if not api_key and Provider(model.provider) is Provider.openai_compatible:
            # Match LiteLLM's OpenAI-compatible fallback when a profile does not
            # name a custom key variable. Adding error capture must not silently
            # turn a previously authenticated executor into an anonymous one.
            api_key = os.environ.get("OPENAI_API_KEY")
        if api_key:
            kwargs["api_key"] = api_key
        timeout_s = ctx.timeout_s if ctx.timeout_s and ctx.timeout_s > 0 else DEFAULT_TIMEOUT_S
        kwargs["timeout"] = timeout_s

        started = time.perf_counter()
        try:
            if (
                _capture_policy(ctx.harness_config) is not None
                and Provider(model.provider) is Provider.openai_compatible
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
            raise HarnessError(
                f"{type(exc).__name__}: {exc}",
                retryable=is_retryable(exc),
                kind="provider_error",
            ) from exc
        latency_ms = int((time.perf_counter() - started) * 1000)

        output_text, usage = _extract(response, latency_ms)
        usage.cost_usd = resolve_cost(response, model, usage, self.pricing_table)
        source_output = output_text
        if _output_adapter(ctx.harness_config) == GUARDRAIL_VERDICT_V1:
            output_text = json.dumps(
                guardrail_verdict_v1(completion=source_output),
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
            "capturing structured HTTP errors requires an OpenAI-compatible base_url",
            retryable=False,
            kind="config",
        )
    payload: dict[str, Any] = {
        "model": model.model_id.removeprefix("openai/"),
        "messages": messages,
        **params,
    }
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
        usage=Usage(latency_ms=latency_ms),
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


def guardrail_verdict_v1(
    *,
    completion: str = "",
    error_body: Mapping[str, Any] | None = None,
    http_status: int | None = None,
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
        "tool_calls": [],
        "stream": None,
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


def headers_from_env(config: Mapping[str, Any]) -> dict[str, str]:
    """Resolve configured request headers while keeping their values out of profiles."""
    headers: dict[str, str] = {}
    for header, env_name in _header_env_names(config).items():
        value = os.environ.get(env_name, "").strip()
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
