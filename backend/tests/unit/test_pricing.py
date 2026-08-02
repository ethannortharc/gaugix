"""Reading rates out of litellm's bundled cost map (no network, ever)."""

from __future__ import annotations

import os

from gaugix.pricing import _candidate_keys, _entry_to_pricing, lookup_pricing


def test_the_bundled_cost_map_is_forced_so_nothing_phones_home():
    """Importing gaugix must pin litellm to its offline map before litellm loads."""
    assert os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] == "True"


def test_candidate_keys_try_bare_then_prefixed():
    assert _candidate_keys("gpt-4o-mini", "openai") == ["gpt-4o-mini", "openai/gpt-4o-mini"]


def test_candidate_keys_strip_an_existing_prefix():
    keys = _candidate_keys("openai/gpt-4o-mini", "openai")
    assert keys[0] == "openai/gpt-4o-mini"
    assert "gpt-4o-mini" in keys


def test_candidate_keys_do_not_repeat_themselves():
    keys = _candidate_keys("openai/gpt-4o-mini", "openai")
    assert len(keys) == len(set(keys))


def test_per_token_rates_become_per_million():
    pricing = _entry_to_pricing(
        {"input_cost_per_token": 1.5e-07, "output_cost_per_token": 6e-07},
    )
    assert pricing is not None
    assert pricing.input_per_1m == 0.15
    assert pricing.output_per_1m == 0.6


def test_a_model_with_no_rates_is_not_priced_at_zero():
    """A confident $0.00 on a paid call is worse than an honest 'unknown'."""
    assert _entry_to_pricing({"input_cost_per_token": 0, "output_cost_per_token": 0}) is None
    assert _entry_to_pricing({"litellm_provider": "openai"}) is None
    assert _entry_to_pricing("not a dict") is None


def test_garbage_rates_are_refused_rather_than_coerced():
    assert _entry_to_pricing({"input_cost_per_token": "free"}) is None


def test_a_well_known_model_resolves():
    pricing = lookup_pricing("gpt-4o-mini", "openai")
    assert pricing is not None
    assert pricing.input_per_1m > 0
    assert pricing.output_per_1m > 0


def test_an_unknown_model_is_none_not_a_guess():
    assert lookup_pricing("totally-made-up-model-9000", "openai") is None
    assert lookup_pricing("", "openai") is None
