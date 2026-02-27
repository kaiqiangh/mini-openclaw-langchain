from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ModelPricing:
    model: str
    input_usd_per_1m: float
    cached_input_usd_per_1m: float
    output_usd_per_1m: float
    source: str


# Pricing snapshot date: 2026-02-27 (manual snapshot for local estimation).
# Costs are estimated in USD per 1M tokens.
_PRICING_TABLE: dict[str, ModelPricing] = {
    # DeepSeek chat/reasoner family (OpenAI-compatible base URL mode).
    "deepseek-chat": ModelPricing(
        model="deepseek-chat",
        input_usd_per_1m=0.28,
        cached_input_usd_per_1m=0.028,
        output_usd_per_1m=0.42,
        source="deepseek-pricing-2026-02-27",
    ),
    "deepseek-reasoner": ModelPricing(
        model="deepseek-reasoner",
        input_usd_per_1m=0.28,
        cached_input_usd_per_1m=0.028,
        output_usd_per_1m=0.42,
        source="deepseek-pricing-2026-02-27",
    ),
    # OpenAI family (fallback if model names are used directly).
    "gpt-5": ModelPricing(
        model="gpt-5",
        input_usd_per_1m=1.25,
        cached_input_usd_per_1m=0.125,
        output_usd_per_1m=10.00,
        source="openai-pricing-2026-02-27",
    ),
    "gpt-5-mini": ModelPricing(
        model="gpt-5-mini",
        input_usd_per_1m=0.25,
        cached_input_usd_per_1m=0.025,
        output_usd_per_1m=2.00,
        source="openai-pricing-2026-02-27",
    ),
    "gpt-5-nano": ModelPricing(
        model="gpt-5-nano",
        input_usd_per_1m=0.05,
        cached_input_usd_per_1m=0.005,
        output_usd_per_1m=0.40,
        source="openai-pricing-2026-02-27",
    ),
    "gpt-4.1": ModelPricing(
        model="gpt-4.1",
        input_usd_per_1m=2.00,
        cached_input_usd_per_1m=0.50,
        output_usd_per_1m=8.00,
        source="openai-pricing-2026-02-27",
    ),
    "gpt-4.1-mini": ModelPricing(
        model="gpt-4.1-mini",
        input_usd_per_1m=0.40,
        cached_input_usd_per_1m=0.10,
        output_usd_per_1m=1.60,
        source="openai-pricing-2026-02-27",
    ),
    "gpt-4.1-nano": ModelPricing(
        model="gpt-4.1-nano",
        input_usd_per_1m=0.10,
        cached_input_usd_per_1m=0.025,
        output_usd_per_1m=0.40,
        source="openai-pricing-2026-02-27",
    ),
    "gpt-4o": ModelPricing(
        model="gpt-4o",
        input_usd_per_1m=2.50,
        cached_input_usd_per_1m=1.25,
        output_usd_per_1m=10.00,
        source="openai-pricing-2026-02-27",
    ),
    "gpt-4o-mini": ModelPricing(
        model="gpt-4o-mini",
        input_usd_per_1m=0.15,
        cached_input_usd_per_1m=0.075,
        output_usd_per_1m=0.60,
        source="openai-pricing-2026-02-27",
    ),
}


def resolve_model_pricing(model: str) -> ModelPricing | None:
    normalized = model.strip().lower()
    if not normalized:
        return None
    if normalized in _PRICING_TABLE:
        return _PRICING_TABLE[normalized]
    for key, pricing in _PRICING_TABLE.items():
        if normalized.startswith(key):
            return pricing
    return None


def estimate_cost_usd(
    *,
    model: str,
    input_tokens: int,
    cached_input_tokens: int,
    output_tokens: int,
) -> dict[str, Any]:
    pricing = resolve_model_pricing(model)
    input_tokens = max(0, int(input_tokens))
    cached_input_tokens = max(0, int(cached_input_tokens))
    output_tokens = max(0, int(output_tokens))
    cached_input_tokens = min(cached_input_tokens, input_tokens)
    uncached_input_tokens = max(0, input_tokens - cached_input_tokens)

    if pricing is None:
        return {
            "model": model,
            "source": "unpriced",
            "uncached_input_tokens": uncached_input_tokens,
            "cached_input_tokens": cached_input_tokens,
            "output_tokens": output_tokens,
            "estimated_cost_usd": 0.0,
        }

    estimated_cost_usd = (
        (uncached_input_tokens / 1_000_000.0) * pricing.input_usd_per_1m
        + (cached_input_tokens / 1_000_000.0) * pricing.cached_input_usd_per_1m
        + (output_tokens / 1_000_000.0) * pricing.output_usd_per_1m
    )
    return {
        "model": model,
        "source": pricing.source,
        "uncached_input_tokens": uncached_input_tokens,
        "cached_input_tokens": cached_input_tokens,
        "output_tokens": output_tokens,
        "estimated_cost_usd": round(estimated_cost_usd, 8),
    }
