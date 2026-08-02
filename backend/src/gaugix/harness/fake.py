"""FakeHarness — a deterministic, zero-cost simulator that ships *in the product*.

Not a test double (PRD F2.5, DECISIONS D-003): it backs the demo seed data, every
dry-run, and the entire test suite, which is why development never costs money.

Configuration (`harness_profile.config_json`):

```jsonc
{
  "mode": "echo" | "script",          // default "echo"
  "script": [                          // consulted in order, first match wins
    {"match": "napalm", "is_regex": false, "response": "{\"action\": \"block\"}"}
  ],
  "default_response": "…",            // used when no script rule matches
  "latency_ms": 0,                     // simulated latency
  "error_rate": 0.0,                   // deterministic pseudo-random failures
  "fail_first_n_invocations": 0,       // the first N invocations always fail
  "fail_if_contains": null,            // fail when the prompt contains this marker
  "error_retryable": true,             // whether injected failures look transient
  "error_message": "injected failure"
}
```

**Determinism contract:** output and failure decisions are a pure function of
(case content, harness config, attempt number). Same inputs → same result, on any
machine, forever. Tests and seeds depend on this.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from typing import Any

from gaugix.domain import (
    CaseSnapshot,
    HarnessError,
    HarnessKind,
    InvocationResult,
    InvokeContext,
    ModelSnapshot,
    Usage,
)
from gaugix.harness.base import estimate_tokens

ECHO_PREFIX = ""


def _canonical_input(case: CaseSnapshot) -> str:
    """The canonicalized input: user turns joined, falling back to the whole prompt."""
    user_parts = [m.content for m in case.input if m.role == "user"]
    if user_parts:
        return "\n\n".join(user_parts)
    return case.prompt_text()


def _unit_float(*parts: str) -> float:
    """Deterministic float in [0, 1) derived from the given strings."""
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / float(1 << 64)


class FakeHarness:
    """Deterministic simulator. See module docstring for the config schema."""

    kind = str(HarnessKind.fake)

    async def invoke(
        self, case: CaseSnapshot, model: ModelSnapshot, ctx: InvokeContext
    ) -> InvocationResult:
        config: dict[str, Any] = dict(ctx.harness_config or {})
        prompt = _canonical_input(case)
        config_key = json.dumps(config, sort_keys=True, default=str)

        latency_ms = int(config.get("latency_ms") or 0)
        if latency_ms > 0:
            await asyncio.sleep(latency_ms / 1000.0)

        self._maybe_fail(case, prompt, config, config_key, ctx)

        output = self._render(prompt, case, config)
        usage = Usage(
            prompt_tokens=estimate_tokens(prompt),
            completion_tokens=estimate_tokens(output),
            cost_usd=0.0,
            latency_ms=latency_ms,
        )
        return InvocationResult(
            output_text=output,
            messages=[*case.messages_for_api(), {"role": "assistant", "content": output}],
            usage=usage,
            raw={
                "harness": "fake",
                "mode": config.get("mode", "echo"),
                "model": model.model_id,
                "attempt_n": ctx.attempt_n,
            },
        )

    # -- internals ---------------------------------------------------------

    def _maybe_fail(
        self,
        case: CaseSnapshot,
        prompt: str,
        config: dict[str, Any],
        config_key: str,
        ctx: InvokeContext,
    ) -> None:
        """Apply the three failure-injection mechanisms, in order of specificity."""
        retryable = bool(config.get("error_retryable", True))
        message = str(config.get("error_message") or "injected failure")

        marker = config.get("fail_if_contains")
        if marker and str(marker) in prompt:
            raise HarnessError(
                f"{message} (fail_if_contains={marker!r})",
                retryable=retryable,
                kind="injected",
            )

        # The invocation ordinal counts retries too, so a value of 1 gives exactly
        # "fail once, then succeed" — the deterministic retry-path fixture.
        fail_first = int(config.get("fail_first_n_invocations") or 0)
        invocation_n = ctx.attempt_n + ctx.try_index
        if fail_first and invocation_n <= fail_first:
            raise HarnessError(
                f"{message} (invocation {invocation_n} <= fail_first_n_invocations={fail_first})",
                retryable=retryable,
                kind="injected",
            )

        error_rate = float(config.get("error_rate") or 0.0)
        if error_rate > 0:
            draw = _unit_float(
                case.content_key(), config_key, str(ctx.attempt_n), str(ctx.try_index)
            )
            if draw < error_rate:
                raise HarnessError(
                    f"{message} (error_rate={error_rate})", retryable=retryable, kind="injected"
                )

    def _render(self, prompt: str, case: CaseSnapshot, config: dict[str, Any]) -> str:
        mode = str(config.get("mode") or "echo")
        if mode == "script":
            for rule in config.get("script") or []:
                if not isinstance(rule, dict):
                    continue
                pattern = str(rule.get("match", ""))
                if not pattern:
                    continue
                if rule.get("is_regex"):
                    try:
                        hit = re.search(pattern, prompt) is not None
                    except re.error:
                        hit = False
                else:
                    hit = pattern.lower() in prompt.lower()
                if hit:
                    return self._expand(str(rule.get("response", "")), case, prompt)
            default = config.get("default_response")
            if default is not None:
                return self._expand(str(default), case, prompt)
            return ECHO_PREFIX + prompt
        if mode == "echo":
            default = config.get("default_response")
            if default is not None:
                return self._expand(str(default), case, prompt)
            return ECHO_PREFIX + prompt
        raise HarnessError(f"unknown fake harness mode: {mode!r}", retryable=False, kind="config")

    @staticmethod
    def _expand(template: str, case: CaseSnapshot, prompt: str) -> str:
        """Substitute the small set of placeholders scripted responses may use."""
        return (
            template.replace("{input}", prompt)
            .replace("{title}", case.title)
            .replace("{reference}", case.reference or "")
        )
