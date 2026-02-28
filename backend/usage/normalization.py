from __future__ import annotations

import math
from typing import Any

from usage.pricing import infer_provider


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _parse_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if math.isfinite(value):
            return int(value)
        return None
    if isinstance(value, str):
        raw = value.strip().replace(",", "")
        if not raw:
            return None
        try:
            return int(raw)
        except Exception:
            try:
                return int(float(raw))
            except Exception:
                return None
    return None


def _path_value(payload: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = payload
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _read_max(payload: dict[str, Any], paths: tuple[tuple[str, ...], ...]) -> int:
    best = 0
    for path in paths:
        parsed = _parse_int(_path_value(payload, path))
        if parsed is None:
            continue
        best = max(best, parsed)
    return best


def _extract_model(response_metadata: dict[str, Any], fallback_model: str) -> tuple[str, str]:
    model_paths: tuple[tuple[str, ...], ...] = (
        ("model_name",),
        ("model",),
        ("model_id",),
        ("modelName",),
        ("response", "model"),
        ("raw", "model"),
    )
    for path in model_paths:
        value = _path_value(response_metadata, path)
        if isinstance(value, str) and value.strip():
            return value.strip(), ".".join(path)
    fallback = fallback_model.strip() or "unknown"
    return fallback, "fallback_model"


def _extract_explicit_provider(response_metadata: dict[str, Any]) -> str | None:
    provider_paths: tuple[tuple[str, ...], ...] = (
        ("provider",),
        ("provider_name",),
        ("providerName",),
        ("llm_provider",),
        ("vendor",),
    )
    for path in provider_paths:
        value = _path_value(response_metadata, path)
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
    return None


def _usage_candidates(
    usage_metadata: dict[str, Any], response_metadata: dict[str, Any]
) -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = []

    if usage_metadata:
        out.append(("usage_metadata", usage_metadata))

    for label, key in (
        ("response_metadata.token_usage", "token_usage"),
        ("response_metadata.usage", "usage"),
        ("response_metadata.usage_metadata", "usage_metadata"),
        ("response_metadata.usageMetadata", "usageMetadata"),
    ):
        payload = _as_dict(response_metadata.get(key))
        if payload:
            out.append((label, payload))

    # Sometimes provider payloads are nested inside additional metadata blobs.
    for label, key in (
        ("response_metadata.raw_usage", "raw_usage"),
        ("response_metadata.llm_output", "llm_output"),
    ):
        payload = _as_dict(response_metadata.get(key))
        nested_usage = _as_dict(payload.get("usage"))
        if nested_usage:
            out.append((f"{label}.usage", nested_usage))

    return out


def extract_usage_from_message(
    *,
    message: Any,
    fallback_model: str,
    fallback_base_url: str | None = None,
) -> dict[str, Any]:
    usage_metadata = _as_dict(getattr(message, "usage_metadata", None))
    response_metadata = _as_dict(getattr(message, "response_metadata", None))

    model, model_source = _extract_model(response_metadata, fallback_model)
    explicit_provider = _extract_explicit_provider(response_metadata)
    provider = infer_provider(
        model,
        base_url=fallback_base_url,
        explicit_provider=explicit_provider,
    )

    input_tokens = 0
    output_tokens = 0
    total_tokens = 0
    cache_read_tokens = 0
    cache_write_5m_tokens = 0
    cache_write_1h_tokens = 0
    cache_write_unknown_tokens = 0
    reasoning_tokens = 0
    tool_input_tokens = 0

    deepseek_cache_hit = 0
    deepseek_cache_miss = 0

    usage_source = ""
    usage_signal = -1

    candidate_list = _usage_candidates(usage_metadata, response_metadata)
    for source, payload in candidate_list:
        candidate_input = _read_max(
            payload,
            (
                ("input_tokens",),
                ("prompt_tokens",),
                ("promptTokenCount",),
                ("prompt_token_count",),
                ("inputTokenCount",),
            ),
        )
        candidate_output = _read_max(
            payload,
            (
                ("output_tokens",),
                ("completion_tokens",),
                ("candidatesTokenCount",),
                ("candidates_token_count",),
                ("outputTokenCount",),
            ),
        )
        candidate_total = _read_max(
            payload,
            (
                ("total_tokens",),
                ("totalTokenCount",),
                ("total_token_count",),
            ),
        )
        candidate_cache_read = _read_max(
            payload,
            (
                ("cache_read_input_tokens",),
                ("cache_read_tokens",),
                ("cached_input_tokens",),
                ("cachedContentTokenCount",),
                ("cached_content_token_count",),
                ("prompt_cache_hit_tokens",),
                ("input_token_details", "cache_read"),
                ("input_token_details", "cached_tokens"),
                ("input_token_details", "cachedTokens"),
                ("prompt_tokens_details", "cache_read"),
                ("prompt_tokens_details", "cached_tokens"),
                ("prompt_tokens_details", "cachedTokens"),
            ),
        )
        candidate_cache_write_5m = _read_max(
            payload,
            (
                ("cache_creation", "ephemeral_5m_input_tokens"),
                ("cache_creation", "5m_input_tokens"),
                ("cache_creation", "ephemeral5mInputTokens"),
                ("cacheCreation", "ephemeral5mInputTokens"),
            ),
        )
        candidate_cache_write_1h = _read_max(
            payload,
            (
                ("cache_creation", "ephemeral_1h_input_tokens"),
                ("cache_creation", "1h_input_tokens"),
                ("cache_creation", "ephemeral1hInputTokens"),
                ("cacheCreation", "ephemeral1hInputTokens"),
            ),
        )
        candidate_cache_write_agg = _read_max(
            payload,
            (
                ("cache_creation_input_tokens",),
                ("cacheCreationInputTokens",),
                ("input_cache_write_tokens",),
            ),
        )
        candidate_reasoning = _read_max(
            payload,
            (
                ("reasoning_tokens",),
                ("thoughtsTokenCount",),
                ("thoughts_token_count",),
                ("output_token_details", "reasoning"),
                ("output_token_details", "reasoning_tokens"),
                ("completion_tokens_details", "reasoning"),
                ("completion_tokens_details", "reasoning_tokens"),
                ("outputTokenDetails", "reasoningTokens"),
            ),
        )
        candidate_tool_input = _read_max(
            payload,
            (
                ("toolUsePromptTokenCount",),
                ("tool_use_prompt_token_count",),
                ("tool_use_prompt_tokens",),
            ),
        )
        candidate_cache_hit = _read_max(
            payload,
            (("prompt_cache_hit_tokens",), ("promptCacheHitTokens",)),
        )
        candidate_cache_miss = _read_max(
            payload,
            (("prompt_cache_miss_tokens",), ("promptCacheMissTokens",)),
        )

        input_tokens = max(input_tokens, candidate_input)
        output_tokens = max(output_tokens, candidate_output)
        total_tokens = max(total_tokens, candidate_total)
        cache_read_tokens = max(cache_read_tokens, candidate_cache_read)
        cache_write_5m_tokens = max(cache_write_5m_tokens, candidate_cache_write_5m)
        cache_write_1h_tokens = max(cache_write_1h_tokens, candidate_cache_write_1h)
        reasoning_tokens = max(reasoning_tokens, candidate_reasoning)
        tool_input_tokens = max(tool_input_tokens, candidate_tool_input)
        deepseek_cache_hit = max(deepseek_cache_hit, candidate_cache_hit)
        deepseek_cache_miss = max(deepseek_cache_miss, candidate_cache_miss)

        if candidate_cache_write_agg > 0:
            known = candidate_cache_write_5m + candidate_cache_write_1h
            remainder = max(0, candidate_cache_write_agg - known)
            cache_write_unknown_tokens = max(cache_write_unknown_tokens, remainder)

        signal = max(
            candidate_total,
            candidate_input + candidate_output + candidate_tool_input,
            candidate_cache_read,
            candidate_reasoning,
        )
        if signal > usage_signal:
            usage_signal = signal
            usage_source = source

    if deepseek_cache_hit > 0:
        cache_read_tokens = max(cache_read_tokens, deepseek_cache_hit)
    if input_tokens <= 0 and (deepseek_cache_hit > 0 or deepseek_cache_miss > 0):
        input_tokens = deepseek_cache_hit + deepseek_cache_miss

    cache_write_total = (
        cache_write_5m_tokens + cache_write_1h_tokens + cache_write_unknown_tokens
    )

    if provider == "anthropic":
        input_uncached_tokens = input_tokens
        input_tokens = input_uncached_tokens + cache_read_tokens + cache_write_total
    elif provider == "deepseek" and deepseek_cache_miss > 0:
        input_uncached_tokens = deepseek_cache_miss
    else:
        input_uncached_tokens = max(0, input_tokens - cache_read_tokens - cache_write_total)

    if input_tokens <= 0 and (
        input_uncached_tokens > 0 or cache_read_tokens > 0 or cache_write_total > 0
    ):
        input_tokens = input_uncached_tokens + cache_read_tokens + cache_write_total

    output_tokens = max(0, output_tokens)
    reasoning_tokens = max(0, reasoning_tokens)
    tool_input_tokens = max(0, tool_input_tokens)

    if provider == "google":
        computed_total = input_tokens + output_tokens + tool_input_tokens + reasoning_tokens
    else:
        computed_total = input_tokens + output_tokens + tool_input_tokens

    if total_tokens <= 0:
        total_tokens = computed_total
    else:
        total_tokens = max(total_tokens, computed_total)

    return {
        "provider": provider,
        "model": model,
        "model_source": model_source,
        "usage_source": usage_source or "unknown",
        "input_tokens": max(0, input_tokens),
        "input_uncached_tokens": max(0, input_uncached_tokens),
        "input_cache_read_tokens": max(0, cache_read_tokens),
        "input_cache_write_tokens_5m": max(0, cache_write_5m_tokens),
        "input_cache_write_tokens_1h": max(0, cache_write_1h_tokens),
        "input_cache_write_tokens_unknown": max(0, cache_write_unknown_tokens),
        "output_tokens": max(0, output_tokens),
        "reasoning_tokens": max(0, reasoning_tokens),
        "tool_input_tokens": max(0, tool_input_tokens),
        "total_tokens": max(0, total_tokens),
    }
