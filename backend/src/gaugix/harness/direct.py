"""DirectHarness — plain chat-completion calls through litellm (ARCHITECTURE §4).

Deliberately thin. Everything provider-specific lives in two places: the model
string mapping and the cost fallback chain. If one provider misbehaves, that is a
litellm problem to route around, not a reason to grow this file.

**Cost is never fabricated.** The chain is litellm's own calculation → the user's
pricing table → `None`. A `None` renders as "n/a" in the UI; a fabricated 0 would
silently corrupt a cost-per-quality comparison.
"""

from __future__ import annotations

import time
from typing import Any

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

        kwargs: dict[str, Any] = {"model": model_string, "messages": messages, **params}
        if model.base_url:
            kwargs["base_url"] = model.base_url
        # litellm will not pick a key up from an arbitrary env var name, so pass it.
        api_key = read_api_key(model.api_key_env)
        if api_key:
            kwargs["api_key"] = api_key
        if ctx.timeout_s:
            kwargs["timeout"] = ctx.timeout_s

        started = time.perf_counter()
        try:
            response = await litellm.acompletion(**kwargs)
        except Exception as exc:
            raise HarnessError(
                f"{type(exc).__name__}: {exc}",
                retryable=is_retryable(exc),
                kind="provider_error",
            ) from exc
        latency_ms = int((time.perf_counter() - started) * 1000)

        output_text, usage = _extract(response, latency_ms)
        usage.cost_usd = resolve_cost(response, model, usage, self.pricing_table)

        return InvocationResult(
            output_text=output_text,
            messages=[*messages, {"role": "assistant", "content": output_text}],
            usage=usage,
            raw={"model": model_string, "provider": str(model.provider)},
        )


def _extract(response: Any, latency_ms: int) -> tuple[str, Usage]:
    """Pull text and token counts out of a litellm response, tolerating shape drift."""
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
