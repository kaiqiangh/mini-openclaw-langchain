from __future__ import annotations

from dataclasses import dataclass
from typing import Any

CATALOG_VERSION = "2026-02-28"


@dataclass(frozen=True)
class ModelPricing:
    provider: str
    model_key: str
    input_usd_per_1m: float
    output_usd_per_1m: float
    cache_read_usd_per_1m: float | None = None
    cache_write_5m_usd_per_1m: float | None = None
    cache_write_1h_usd_per_1m: float | None = None
    long_context_threshold_tokens: int | None = None
    long_context_input_usd_per_1m: float | None = None
    long_context_output_usd_per_1m: float | None = None
    long_context_cache_read_usd_per_1m: float | None = None
    long_context_cache_write_5m_usd_per_1m: float | None = None
    long_context_cache_write_1h_usd_per_1m: float | None = None
    source: str = ""


def _p(
    provider: str,
    model_key: str,
    input_rate: float,
    output_rate: float,
    *,
    cache_read_rate: float | None = None,
    cache_write_5m_rate: float | None = None,
    cache_write_1h_rate: float | None = None,
    long_context_threshold_tokens: int | None = None,
    long_context_input_rate: float | None = None,
    long_context_output_rate: float | None = None,
    long_context_cache_read_rate: float | None = None,
    long_context_cache_write_5m_rate: float | None = None,
    long_context_cache_write_1h_rate: float | None = None,
    source: str,
) -> ModelPricing:
    return ModelPricing(
        provider=provider,
        model_key=model_key,
        input_usd_per_1m=input_rate,
        output_usd_per_1m=output_rate,
        cache_read_usd_per_1m=cache_read_rate,
        cache_write_5m_usd_per_1m=cache_write_5m_rate,
        cache_write_1h_usd_per_1m=cache_write_1h_rate,
        long_context_threshold_tokens=long_context_threshold_tokens,
        long_context_input_usd_per_1m=long_context_input_rate,
        long_context_output_usd_per_1m=long_context_output_rate,
        long_context_cache_read_usd_per_1m=long_context_cache_read_rate,
        long_context_cache_write_5m_usd_per_1m=long_context_cache_write_5m_rate,
        long_context_cache_write_1h_usd_per_1m=long_context_cache_write_1h_rate,
        source=source,
    )


# Source references used to build this catalog:
# - OpenAI API pricing: https://openai.com/api/pricing/
# - Anthropic pricing + prompt caching:
#   https://docs.anthropic.com/en/docs/about-claude/pricing
#   https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching
# - Gemini Developer API pricing: https://ai.google.dev/gemini-api/docs/pricing
# - DeepSeek pricing: https://api-docs.deepseek.com/quick_start/pricing/
_PRICING_TABLE: dict[str, tuple[ModelPricing, ...]] = {
    "openai": (
        _p(
            "openai",
            "gpt-5",
            1.25,
            10.00,
            cache_read_rate=0.125,
            source="openai-pricing-2026-02-28",
        ),
        _p(
            "openai",
            "gpt-5-mini",
            0.25,
            2.00,
            cache_read_rate=0.025,
            source="openai-pricing-2026-02-28",
        ),
        _p(
            "openai",
            "gpt-5-nano",
            0.05,
            0.40,
            cache_read_rate=0.005,
            source="openai-pricing-2026-02-28",
        ),
        _p(
            "openai",
            "gpt-4.1",
            2.00,
            8.00,
            cache_read_rate=0.50,
            source="openai-pricing-2026-02-28",
        ),
        _p(
            "openai",
            "gpt-4.1-mini",
            0.40,
            1.60,
            cache_read_rate=0.10,
            source="openai-pricing-2026-02-28",
        ),
        _p(
            "openai",
            "gpt-4.1-nano",
            0.10,
            0.40,
            cache_read_rate=0.025,
            source="openai-pricing-2026-02-28",
        ),
        _p(
            "openai",
            "gpt-4o",
            2.50,
            10.00,
            cache_read_rate=1.25,
            source="openai-pricing-2026-02-28",
        ),
        _p(
            "openai",
            "gpt-4o-mini",
            0.15,
            0.60,
            cache_read_rate=0.075,
            source="openai-pricing-2026-02-28",
        ),
    ),
    "anthropic": (
        _p(
            "anthropic",
            "claude-opus-4-1",
            15.0,
            75.0,
            cache_read_rate=1.50,
            cache_write_5m_rate=18.75,
            cache_write_1h_rate=30.0,
            source="anthropic-pricing-2026-02-28",
        ),
        _p(
            "anthropic",
            "claude-opus-4",
            15.0,
            75.0,
            cache_read_rate=1.50,
            cache_write_5m_rate=18.75,
            cache_write_1h_rate=30.0,
            source="anthropic-pricing-2026-02-28",
        ),
        _p(
            "anthropic",
            "claude-sonnet-4",
            3.0,
            15.0,
            cache_read_rate=0.30,
            cache_write_5m_rate=3.75,
            cache_write_1h_rate=6.0,
            long_context_threshold_tokens=200_000,
            long_context_input_rate=6.0,
            long_context_output_rate=22.5,
            long_context_cache_read_rate=0.60,
            long_context_cache_write_5m_rate=7.5,
            long_context_cache_write_1h_rate=12.0,
            source="anthropic-pricing-2026-02-28",
        ),
        _p(
            "anthropic",
            "claude-sonnet-3-7",
            3.0,
            15.0,
            cache_read_rate=0.30,
            cache_write_5m_rate=3.75,
            cache_write_1h_rate=6.0,
            source="anthropic-pricing-2026-02-28",
        ),
        _p(
            "anthropic",
            "claude-haiku-3-5",
            0.80,
            4.0,
            cache_read_rate=0.08,
            cache_write_5m_rate=1.0,
            cache_write_1h_rate=1.6,
            source="anthropic-pricing-2026-02-28",
        ),
        _p(
            "anthropic",
            "claude-haiku-3",
            0.25,
            1.25,
            cache_read_rate=0.025,
            cache_write_5m_rate=0.3125,
            cache_write_1h_rate=0.50,
            source="anthropic-pricing-2026-02-28",
        ),
    ),
    "google": (
        _p(
            "google",
            "gemini-2.5-pro",
            1.25,
            10.0,
            cache_read_rate=0.125,
            long_context_threshold_tokens=200_000,
            long_context_input_rate=2.50,
            long_context_output_rate=15.0,
            long_context_cache_read_rate=0.25,
            source="google-gemini-pricing-2026-02-28",
        ),
        _p(
            "google",
            "gemini-2.5-flash",
            0.30,
            2.50,
            cache_read_rate=0.03,
            source="google-gemini-pricing-2026-02-28",
        ),
        _p(
            "google",
            "gemini-2.5-flash-lite",
            0.10,
            0.40,
            cache_read_rate=0.01,
            source="google-gemini-pricing-2026-02-28",
        ),
    ),
    "deepseek": (
        _p(
            "deepseek",
            "deepseek-chat",
            0.28,
            0.42,
            cache_read_rate=0.028,
            source="deepseek-pricing-2026-02-28",
        ),
        _p(
            "deepseek",
            "deepseek-reasoner",
            0.28,
            0.42,
            cache_read_rate=0.028,
            source="deepseek-pricing-2026-02-28",
        ),
    ),
}

_PROVIDER_PREFIXES: dict[str, tuple[str, ...]] = {
    "openai": ("openai", "gpt-", "o1", "o3", "o4"),
    "anthropic": ("anthropic", "claude-"),
    "google": ("google", "gemini-"),
    "deepseek": ("deepseek", "deepseek-"),
}


def _normalized(value: str) -> str:
    return value.strip().lower()


def _strip_provider_prefix(model: str) -> str:
    normalized = _normalized(model)
    for sep in ("/", ":"):
        if sep in normalized:
            head, tail = normalized.split(sep, 1)
            if head in _PROVIDER_PREFIXES:
                return tail.strip()
    return normalized


def infer_provider(
    model: str,
    *,
    base_url: str | None = None,
    explicit_provider: str | None = None,
) -> str:
    if explicit_provider:
        normalized_provider = _normalized(explicit_provider)
        if normalized_provider in _PROVIDER_PREFIXES:
            return normalized_provider

    normalized_model = _normalized(model)
    if "/" in normalized_model or ":" in normalized_model:
        for sep in ("/", ":"):
            if sep in normalized_model:
                head = normalized_model.split(sep, 1)[0]
                if head in _PROVIDER_PREFIXES:
                    return head

    for provider, prefixes in _PROVIDER_PREFIXES.items():
        for prefix in prefixes:
            if normalized_model.startswith(prefix):
                return provider

    normalized_url = _normalized(base_url or "")
    if "deepseek" in normalized_url:
        return "deepseek"
    if "anthropic" in normalized_url:
        return "anthropic"
    if "google" in normalized_url or "vertex" in normalized_url:
        return "google"
    if "openai" in normalized_url:
        return "openai"
    return "unknown"


def resolve_model_pricing(provider: str, model: str) -> ModelPricing | None:
    normalized_provider = _normalized(provider)
    pricing_rows = _PRICING_TABLE.get(normalized_provider)
    if not pricing_rows:
        return None

    normalized_model = _strip_provider_prefix(model)
    if not normalized_model:
        return None

    exact_match: ModelPricing | None = None
    for pricing in pricing_rows:
        key = _normalized(pricing.model_key)
        if normalized_model == key:
            exact_match = pricing
            break
    if exact_match is not None:
        return exact_match

    # Prefix matching supports versioned snapshots like gpt-5-2026-01-01.
    for pricing in pricing_rows:
        key = _normalized(pricing.model_key)
        if normalized_model.startswith(key):
            return pricing
    return None


def _line_item(kind: str, tokens: int, rate: float | None) -> dict[str, Any]:
    line: dict[str, Any] = {
        "kind": kind,
        "tokens": max(0, int(tokens)),
        "rate_usd_per_1m": rate,
        "cost_usd": None,
    }
    if line["tokens"] <= 0:
        return line
    if rate is None:
        return line
    line["cost_usd"] = round((line["tokens"] / 1_000_000.0) * rate, 8)
    return line


def calculate_cost_breakdown(
    *,
    provider: str,
    model: str,
    input_tokens: int,
    input_uncached_tokens: int,
    input_cache_read_tokens: int,
    input_cache_write_tokens_5m: int,
    input_cache_write_tokens_1h: int,
    input_cache_write_tokens_unknown: int,
    output_tokens: int,
) -> dict[str, Any]:
    normalized_provider = _normalized(provider)
    normalized_model = _normalized(model)

    input_tokens = max(0, int(input_tokens))
    input_uncached_tokens = max(0, int(input_uncached_tokens))
    input_cache_read_tokens = max(0, int(input_cache_read_tokens))
    input_cache_write_tokens_5m = max(0, int(input_cache_write_tokens_5m))
    input_cache_write_tokens_1h = max(0, int(input_cache_write_tokens_1h))
    input_cache_write_tokens_unknown = max(0, int(input_cache_write_tokens_unknown))
    output_tokens = max(0, int(output_tokens))

    pricing = resolve_model_pricing(normalized_provider, normalized_model)
    if pricing is None:
        return {
            "provider": normalized_provider,
            "model": model,
            "model_key": None,
            "priced": False,
            "currency": "USD",
            "source": "unpriced",
            "catalog_version": CATALOG_VERSION,
            "long_context_applied": False,
            "line_items": [
                _line_item("input_uncached", input_uncached_tokens, None),
                _line_item("input_cache_read", input_cache_read_tokens, None),
                _line_item("input_cache_write_5m", input_cache_write_tokens_5m, None),
                _line_item("input_cache_write_1h", input_cache_write_tokens_1h, None),
                _line_item(
                    "input_cache_write_unknown", input_cache_write_tokens_unknown, None
                ),
                _line_item("output", output_tokens, None),
            ],
            "total_cost_usd": None,
            "unpriced_reason": "model_not_in_catalog",
        }

    long_context_applied = False
    input_rate = pricing.input_usd_per_1m
    output_rate = pricing.output_usd_per_1m
    cache_read_rate = pricing.cache_read_usd_per_1m
    cache_write_5m_rate = pricing.cache_write_5m_usd_per_1m
    cache_write_1h_rate = pricing.cache_write_1h_usd_per_1m

    if (
        pricing.long_context_threshold_tokens is not None
        and input_tokens > pricing.long_context_threshold_tokens
    ):
        long_context_applied = True
        if (
            pricing.long_context_input_usd_per_1m is None
            or pricing.long_context_output_usd_per_1m is None
        ):
            return {
                "provider": normalized_provider,
                "model": model,
                "model_key": pricing.model_key,
                "priced": False,
                "currency": "USD",
                "source": pricing.source,
                "catalog_version": CATALOG_VERSION,
                "long_context_applied": True,
                "line_items": [
                    _line_item("input_uncached", input_uncached_tokens, None),
                    _line_item("input_cache_read", input_cache_read_tokens, None),
                    _line_item(
                        "input_cache_write_5m", input_cache_write_tokens_5m, None
                    ),
                    _line_item(
                        "input_cache_write_1h", input_cache_write_tokens_1h, None
                    ),
                    _line_item(
                        "input_cache_write_unknown",
                        input_cache_write_tokens_unknown,
                        None,
                    ),
                    _line_item("output", output_tokens, None),
                ],
                "total_cost_usd": None,
                "unpriced_reason": "long_context_rates_missing",
            }

        input_rate = pricing.long_context_input_usd_per_1m
        output_rate = pricing.long_context_output_usd_per_1m
        cache_read_rate = (
            pricing.long_context_cache_read_usd_per_1m
            if pricing.long_context_cache_read_usd_per_1m is not None
            else pricing.cache_read_usd_per_1m
        )
        cache_write_5m_rate = (
            pricing.long_context_cache_write_5m_usd_per_1m
            if pricing.long_context_cache_write_5m_usd_per_1m is not None
            else pricing.cache_write_5m_usd_per_1m
        )
        cache_write_1h_rate = (
            pricing.long_context_cache_write_1h_usd_per_1m
            if pricing.long_context_cache_write_1h_usd_per_1m is not None
            else pricing.cache_write_1h_usd_per_1m
        )

    lines = [
        _line_item("input_uncached", input_uncached_tokens, input_rate),
        _line_item("input_cache_read", input_cache_read_tokens, cache_read_rate),
        _line_item("input_cache_write_5m", input_cache_write_tokens_5m, cache_write_5m_rate),
        _line_item("input_cache_write_1h", input_cache_write_tokens_1h, cache_write_1h_rate),
        _line_item("input_cache_write_unknown", input_cache_write_tokens_unknown, None),
        _line_item("output", output_tokens, output_rate),
    ]

    unpriced_reasons: list[str] = []
    if input_cache_read_tokens > 0 and cache_read_rate is None:
        unpriced_reasons.append("cache_read_rate_missing")
    if input_cache_write_tokens_5m > 0 and cache_write_5m_rate is None:
        unpriced_reasons.append("cache_write_5m_rate_missing")
    if input_cache_write_tokens_1h > 0 and cache_write_1h_rate is None:
        unpriced_reasons.append("cache_write_1h_rate_missing")
    if input_cache_write_tokens_unknown > 0:
        unpriced_reasons.append("cache_write_ttl_unknown")

    total_cost_usd = 0.0
    for line in lines:
        cost = line.get("cost_usd")
        tokens = int(line.get("tokens", 0))
        if tokens <= 0:
            continue
        if cost is None:
            unpriced_reasons.append(f"rate_missing_for_{line.get('kind', 'unknown')}")
            continue
        total_cost_usd += float(cost)

    # Deduplicate while preserving order.
    seen: set[str] = set()
    deduped_reasons: list[str] = []
    for reason in unpriced_reasons:
        if reason in seen:
            continue
        seen.add(reason)
        deduped_reasons.append(reason)

    priced = len(deduped_reasons) == 0
    return {
        "provider": normalized_provider,
        "model": model,
        "model_key": pricing.model_key,
        "priced": priced,
        "currency": "USD",
        "source": pricing.source,
        "catalog_version": CATALOG_VERSION,
        "long_context_applied": long_context_applied,
        "line_items": lines,
        "total_cost_usd": round(total_cost_usd, 8) if priced else None,
        "unpriced_reason": ",".join(deduped_reasons) if deduped_reasons else None,
    }
