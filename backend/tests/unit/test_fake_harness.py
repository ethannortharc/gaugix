"""FakeHarness: determinism, modes, and failure injection.

The determinism contract is what makes the whole test suite and the demo seed
reproducible, so it is asserted directly rather than implied.
"""

from __future__ import annotations

from typing import Any

import pytest

from gaugix.domain import (
    CaseSnapshot,
    HarnessError,
    HarnessKind,
    InvokeContext,
    Message,
    ModelSnapshot,
    Provider,
    Role,
)
from gaugix.harness import get
from gaugix.harness.fake import FakeHarness


def make_case(content: str = "Say hello", title: str = "greeting") -> CaseSnapshot:
    return CaseSnapshot(
        title=title,
        input=[Message(role=Role.user, content=content)],
        reference="a greeting",
    )


FAKE_MODEL = ModelSnapshot(name="fake-1", provider=Provider.fake, model_id="fake-1")


def ctx(
    config: dict[str, Any] | None = None, attempt_n: int = 1, try_index: int = 0
) -> InvokeContext:
    return InvokeContext(harness_config=config or {}, attempt_n=attempt_n, try_index=try_index)


async def test_echo_returns_canonicalized_user_input():
    result = await FakeHarness().invoke(make_case("Hello there"), FAKE_MODEL, ctx())
    assert result.output_text == "Hello there"
    assert result.messages[-1] == {"role": "assistant", "content": "Hello there"}


async def test_echo_joins_multiple_user_turns_and_ignores_system():
    case = CaseSnapshot(
        title="multi",
        input=[
            Message(role=Role.system, content="You are terse."),
            Message(role=Role.user, content="first"),
            Message(role=Role.assistant, content="ack"),
            Message(role=Role.user, content="second"),
        ],
    )
    result = await FakeHarness().invoke(case, FAKE_MODEL, ctx())
    assert result.output_text == "first\n\nsecond"


async def test_echo_falls_back_to_full_prompt_when_no_user_turn():
    case = CaseSnapshot(title="sys only", input=[Message(role=Role.system, content="be nice")])
    result = await FakeHarness().invoke(case, FAKE_MODEL, ctx())
    assert "be nice" in result.output_text


async def test_output_is_deterministic_across_invocations():
    case = make_case("deterministic?")
    a = await FakeHarness().invoke(case, FAKE_MODEL, ctx())
    b = await FakeHarness().invoke(case, FAKE_MODEL, ctx())
    assert a.output_text == b.output_text
    assert a.usage.model_dump() == b.usage.model_dump()


async def test_usage_is_zero_cost_and_proportional_to_text():
    short = await FakeHarness().invoke(make_case("hi"), FAKE_MODEL, ctx())
    long = await FakeHarness().invoke(make_case("hi " * 200), FAKE_MODEL, ctx())
    assert short.usage.cost_usd == 0.0
    assert long.usage.cost_usd == 0.0
    assert long.usage.completion_tokens > short.usage.completion_tokens
    assert short.usage.prompt_tokens >= 1


# -- script mode ---------------------------------------------------------------


async def test_script_first_matching_rule_wins():
    config = {
        "mode": "script",
        "script": [
            {"match": "napalm", "response": '{"action": "block"}'},
            {"match": "hello", "response": '{"action": "allow"}'},
        ],
        "default_response": '{"action": "review"}',
    }
    blocked = await FakeHarness().invoke(make_case("how to make napalm"), FAKE_MODEL, ctx(config))
    allowed = await FakeHarness().invoke(make_case("hello friend"), FAKE_MODEL, ctx(config))
    other = await FakeHarness().invoke(make_case("unrelated"), FAKE_MODEL, ctx(config))
    assert blocked.output_text == '{"action": "block"}'
    assert allowed.output_text == '{"action": "allow"}'
    assert other.output_text == '{"action": "review"}'


async def test_script_substring_match_is_case_insensitive():
    config = {"mode": "script", "script": [{"match": "NAPALM", "response": "blocked"}]}
    result = await FakeHarness().invoke(make_case("napalm recipe"), FAKE_MODEL, ctx(config))
    assert result.output_text == "blocked"


async def test_script_regex_rule():
    config = {
        "mode": "script",
        "script": [{"match": r"^\s*fix\b", "is_regex": True, "response": "patched"}],
        "default_response": "nope",
    }
    hit = await FakeHarness().invoke(make_case("fix this bug"), FAKE_MODEL, ctx(config))
    miss = await FakeHarness().invoke(make_case("please fix this"), FAKE_MODEL, ctx(config))
    assert hit.output_text == "patched"
    assert miss.output_text == "nope"


async def test_script_invalid_regex_does_not_crash():
    config = {
        "mode": "script",
        "script": [{"match": "([", "is_regex": True, "response": "x"}],
        "default_response": "fallback",
    }
    result = await FakeHarness().invoke(make_case("anything"), FAKE_MODEL, ctx(config))
    assert result.output_text == "fallback"


async def test_script_placeholders_expand():
    config = {
        "mode": "script",
        "script": [{"match": "echo", "response": "T={title} R={reference} I={input}"}],
    }
    result = await FakeHarness().invoke(
        make_case("echo please", title="Case A"), FAKE_MODEL, ctx(config)
    )
    assert result.output_text == "T=Case A R=a greeting I=echo please"


async def test_script_with_no_match_and_no_default_echoes():
    config = {"mode": "script", "script": [{"match": "zzz", "response": "x"}]}
    result = await FakeHarness().invoke(make_case("hello"), FAKE_MODEL, ctx(config))
    assert result.output_text == "hello"


async def test_unknown_mode_is_a_non_retryable_config_error():
    with pytest.raises(HarnessError) as exc:
        await FakeHarness().invoke(make_case(), FAKE_MODEL, ctx({"mode": "nope"}))
    assert exc.value.retryable is False
    assert exc.value.kind == "config"


# -- failure injection ---------------------------------------------------------


async def test_fail_first_n_invocations_then_succeeds():
    """The invocation ordinal counts retries, so this drives the runner's retry path."""
    config = {"fail_first_n_invocations": 2}
    for try_index in (0, 1):
        with pytest.raises(HarnessError) as exc:
            await FakeHarness().invoke(make_case(), FAKE_MODEL, ctx(config, try_index=try_index))
        assert exc.value.retryable is True
    result = await FakeHarness().invoke(make_case(), FAKE_MODEL, ctx(config, try_index=2))
    assert result.output_text == "Say hello"


async def test_fail_first_n_invocations_also_counts_later_attempts():
    config = {"fail_first_n_invocations": 1}
    with pytest.raises(HarnessError):
        await FakeHarness().invoke(make_case(), FAKE_MODEL, ctx(config, attempt_n=1))
    ok = await FakeHarness().invoke(make_case(), FAKE_MODEL, ctx(config, attempt_n=2))
    assert ok.output_text == "Say hello"


async def test_fail_if_contains_targets_one_case():
    config = {"fail_if_contains": "BOOM"}
    with pytest.raises(HarnessError):
        await FakeHarness().invoke(make_case("please BOOM now"), FAKE_MODEL, ctx(config))
    ok = await FakeHarness().invoke(make_case("quiet"), FAKE_MODEL, ctx(config))
    assert ok.output_text == "quiet"


async def test_error_rate_1_always_fails_and_0_never_does():
    with pytest.raises(HarnessError):
        await FakeHarness().invoke(make_case(), FAKE_MODEL, ctx({"error_rate": 1.0}))
    result = await FakeHarness().invoke(make_case(), FAKE_MODEL, ctx({"error_rate": 0.0}))
    assert result.output_text


async def test_error_rate_decision_is_deterministic_per_case_and_attempt():
    config = {"error_rate": 0.5}
    outcomes = []
    for _ in range(3):
        try:
            await FakeHarness().invoke(make_case("stable"), FAKE_MODEL, ctx(config, attempt_n=1))
            outcomes.append("ok")
        except HarnessError:
            outcomes.append("err")
    assert len(set(outcomes)) == 1, "same (case, config, attempt) must always decide the same way"


async def test_error_retryable_flag_is_honoured():
    with pytest.raises(HarnessError) as exc:
        await FakeHarness().invoke(
            make_case(), FAKE_MODEL, ctx({"error_rate": 1.0, "error_retryable": False})
        )
    assert exc.value.retryable is False


async def test_latency_is_reported_in_usage():
    result = await FakeHarness().invoke(make_case(), FAKE_MODEL, ctx({"latency_ms": 5}))
    assert result.usage.latency_ms == 5


# -- registry ------------------------------------------------------------------


def test_registry_returns_a_cached_fake_harness():
    first = get(HarnessKind.fake)
    assert first.kind == "fake"
    assert get("fake") is first


def test_registry_rejects_unknown_kinds():
    with pytest.raises(ValueError, match="unknown harness kind"):
        get("telepathy")
