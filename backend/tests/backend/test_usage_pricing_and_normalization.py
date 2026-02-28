from __future__ import annotations

from types import SimpleNamespace

from graph.agent import AgentManager
from usage.normalization import extract_usage_from_message
from usage.pricing import calculate_cost_breakdown


def _msg(*, usage_metadata=None, response_metadata=None):
    return SimpleNamespace(
        usage_metadata=usage_metadata or {},
        response_metadata=response_metadata or {},
    )


def test_normalization_openai_with_cached_and_reasoning_details():
    message = _msg(
        usage_metadata={
            "input_tokens": 100,
            "output_tokens": 30,
            "total_tokens": 130,
        },
        response_metadata={
            "model_name": "gpt-5-mini-2026-01-01",
            "token_usage": {
                "prompt_tokens": 100,
                "completion_tokens": 30,
                "total_tokens": 130,
                "prompt_tokens_details": {"cached_tokens": 20},
                "completion_tokens_details": {"reasoning_tokens": 8},
            },
        },
    )

    usage = extract_usage_from_message(
        message=message,
        fallback_model="deepseek-chat",
        fallback_base_url="https://api.openai.com/v1",
    )

    assert usage["provider"] == "openai"
    assert usage["model"] == "gpt-5-mini-2026-01-01"
    assert usage["input_tokens"] == 100
    assert usage["input_cache_read_tokens"] == 20
    assert usage["input_uncached_tokens"] == 80
    assert usage["output_tokens"] == 30
    assert usage["reasoning_tokens"] == 8
    assert usage["total_tokens"] == 130


def test_normalization_anthropic_cache_creation_and_read():
    message = _msg(
        response_metadata={
            "model": "claude-sonnet-4-20250514",
            "usage": {
                "input_tokens": 21,
                "output_tokens": 393,
                "cache_creation_input_tokens": 188_086,
                "cache_read_input_tokens": 100,
            },
        }
    )

    usage = extract_usage_from_message(
        message=message,
        fallback_model="deepseek-chat",
        fallback_base_url="https://api.anthropic.com",
    )

    assert usage["provider"] == "anthropic"
    assert usage["input_uncached_tokens"] == 21
    assert usage["input_cache_read_tokens"] == 100
    assert usage["input_cache_write_tokens_unknown"] == 188_086
    assert usage["input_tokens"] == 188_207
    assert usage["output_tokens"] == 393


def test_normalization_deepseek_hit_miss_mapping():
    message = _msg(
        response_metadata={
            "model": "deepseek-chat",
            "usage": {
                "prompt_tokens": 260,
                "completion_tokens": 44,
                "total_tokens": 304,
                "prompt_cache_hit_tokens": 200,
                "prompt_cache_miss_tokens": 60,
            },
        }
    )

    usage = extract_usage_from_message(
        message=message,
        fallback_model="deepseek-chat",
        fallback_base_url="https://api.deepseek.com/v1",
    )

    assert usage["provider"] == "deepseek"
    assert usage["input_tokens"] == 260
    assert usage["input_cache_read_tokens"] == 200
    assert usage["input_uncached_tokens"] == 60
    assert usage["output_tokens"] == 44
    assert usage["total_tokens"] == 304


def test_cost_breakdown_openai_priced():
    cost = calculate_cost_breakdown(
        provider="openai",
        model="gpt-5-mini",
        input_tokens=100,
        input_uncached_tokens=80,
        input_cache_read_tokens=20,
        input_cache_write_tokens_5m=0,
        input_cache_write_tokens_1h=0,
        input_cache_write_tokens_unknown=0,
        output_tokens=30,
    )

    assert cost["priced"] is True
    assert cost["total_cost_usd"] is not None
    # (80 * 0.25 + 20 * 0.025 + 30 * 2.0) / 1_000_000 = 0.0000805
    assert abs(float(cost["total_cost_usd"]) - 0.0000805) < 1e-8


def test_cost_breakdown_long_context_anthropic_sonnet4():
    cost = calculate_cost_breakdown(
        provider="anthropic",
        model="claude-sonnet-4-20250514",
        input_tokens=250_000,
        input_uncached_tokens=60_000,
        input_cache_read_tokens=100_000,
        input_cache_write_tokens_5m=50_000,
        input_cache_write_tokens_1h=40_000,
        input_cache_write_tokens_unknown=0,
        output_tokens=10_000,
    )

    assert cost["priced"] is True
    assert cost["long_context_applied"] is True
    assert cost["total_cost_usd"] is not None


def test_cost_breakdown_unpriced_unknown_model():
    cost = calculate_cost_breakdown(
        provider="google",
        model="gemini-unknown-x",
        input_tokens=100,
        input_uncached_tokens=100,
        input_cache_read_tokens=0,
        input_cache_write_tokens_5m=0,
        input_cache_write_tokens_1h=0,
        input_cache_write_tokens_unknown=0,
        output_tokens=20,
    )

    assert cost["priced"] is False
    assert cost["total_cost_usd"] is None
    assert cost["unpriced_reason"] == "model_not_in_catalog"


def test_usage_accumulator_sums_distinct_calls_and_dedupes_replays():
    manager = AgentManager()
    usage_state = {
        "provider": "deepseek",
        "model": "deepseek-chat",
        "model_source": "fallback_model",
        "usage_source": "unknown",
        "input_tokens": 0,
        "input_uncached_tokens": 0,
        "input_cache_read_tokens": 0,
        "input_cache_write_tokens_5m": 0,
        "input_cache_write_tokens_1h": 0,
        "input_cache_write_tokens_unknown": 0,
        "output_tokens": 0,
        "reasoning_tokens": 0,
        "tool_input_tokens": 0,
        "total_tokens": 0,
    }
    usage_sources: dict[str, dict[str, int]] = {}

    call_a = {
        "provider": "deepseek",
        "model": "deepseek-chat",
        "model_source": "model_name",
        "usage_source": "usage_metadata",
        "input_tokens": 100,
        "input_uncached_tokens": 40,
        "input_cache_read_tokens": 60,
        "output_tokens": 10,
        "total_tokens": 110,
    }
    replay_of_call_a = dict(call_a)
    call_b = dict(call_a)

    changed = manager._accumulate_usage_candidate(
        usage_state=usage_state,
        usage_sources=usage_sources,
        source_id="call-a",
        usage_candidate=call_a,
    )
    assert changed is True

    # Same source + same usage should not inflate totals.
    changed = manager._accumulate_usage_candidate(
        usage_state=usage_state,
        usage_sources=usage_sources,
        source_id="call-a",
        usage_candidate=replay_of_call_a,
    )
    assert changed is False

    # Same shape of usage from a different call should be counted.
    changed = manager._accumulate_usage_candidate(
        usage_state=usage_state,
        usage_sources=usage_sources,
        source_id="call-b",
        usage_candidate=call_b,
    )
    assert changed is True

    assert usage_state["input_tokens"] == 200
    assert usage_state["input_uncached_tokens"] == 80
    assert usage_state["input_cache_read_tokens"] == 120
    assert usage_state["output_tokens"] == 20
    assert usage_state["total_tokens"] == 220
