from __future__ import annotations

from typing import Any

from config import AppConfig
from storage.usage_store import UsageStore
from usage.normalization import extract_usage_from_message
from usage.pricing import calculate_cost_breakdown


class UsageOrchestrator:
    @staticmethod
    def initial_usage_state(*, provider: str, model: str) -> dict[str, Any]:
        return {
            "provider": provider,
            "model": model,
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

    @staticmethod
    def as_int(value: Any) -> int:
        try:
            return int(value)
        except Exception:
            return 0

    @staticmethod
    def as_dict(value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    @staticmethod
    def usage_numeric_fields() -> tuple[str, ...]:
        return (
            "input_tokens",
            "input_uncached_tokens",
            "input_cache_read_tokens",
            "input_cache_write_tokens_5m",
            "input_cache_write_tokens_1h",
            "input_cache_write_tokens_unknown",
            "output_tokens",
            "reasoning_tokens",
            "tool_input_tokens",
            "total_tokens",
        )

    def merge_usage_identity(
        self, usage_state: dict[str, Any], usage_candidate: dict[str, Any]
    ) -> None:
        for field in ("provider", "model", "model_source", "usage_source"):
            value = str(usage_candidate.get(field, "")).strip()
            if not value:
                continue
            current = str(usage_state.get(field, "")).strip()
            if value.lower() == "unknown" and current and current.lower() != "unknown":
                continue
            if (
                current
                and current.lower() != "unknown"
                and value.lower() != "unknown"
                and current != value
            ):
                if field in {"provider", "model"}:
                    usage_state[field] = "mixed"
                    continue
                continue
            usage_state[field] = value

    def normalize_aggregated_usage(self, usage_state: dict[str, Any]) -> None:
        input_tokens = self.as_int(usage_state.get("input_tokens", 0))
        input_uncached_tokens = self.as_int(usage_state.get("input_uncached_tokens", 0))
        cache_read_tokens = self.as_int(usage_state.get("input_cache_read_tokens", 0))
        cache_write_5m_tokens = self.as_int(
            usage_state.get("input_cache_write_tokens_5m", 0)
        )
        cache_write_1h_tokens = self.as_int(
            usage_state.get("input_cache_write_tokens_1h", 0)
        )
        cache_write_unknown_tokens = self.as_int(
            usage_state.get("input_cache_write_tokens_unknown", 0)
        )
        output_tokens = self.as_int(usage_state.get("output_tokens", 0))
        reasoning_tokens = self.as_int(usage_state.get("reasoning_tokens", 0))
        tool_input_tokens = self.as_int(usage_state.get("tool_input_tokens", 0))
        total_tokens = self.as_int(usage_state.get("total_tokens", 0))

        cache_write_total = (
            cache_write_5m_tokens + cache_write_1h_tokens + cache_write_unknown_tokens
        )

        if input_tokens <= 0 and (
            input_uncached_tokens > 0 or cache_read_tokens > 0 or cache_write_total > 0
        ):
            input_tokens = input_uncached_tokens + cache_read_tokens + cache_write_total

        if input_uncached_tokens <= 0 and input_tokens > 0:
            input_uncached_tokens = max(
                0, input_tokens - cache_read_tokens - cache_write_total
            )

        if input_uncached_tokens > input_tokens:
            input_uncached_tokens = input_tokens

        computed_total = (
            input_tokens + output_tokens + tool_input_tokens + reasoning_tokens
        )
        if total_tokens <= 0:
            total_tokens = computed_total
        else:
            total_tokens = max(total_tokens, computed_total)

        usage_state["input_tokens"] = input_tokens
        usage_state["input_uncached_tokens"] = input_uncached_tokens
        usage_state["input_cache_read_tokens"] = cache_read_tokens
        usage_state["input_cache_write_tokens_5m"] = cache_write_5m_tokens
        usage_state["input_cache_write_tokens_1h"] = cache_write_1h_tokens
        usage_state["input_cache_write_tokens_unknown"] = cache_write_unknown_tokens
        usage_state["output_tokens"] = output_tokens
        usage_state["reasoning_tokens"] = reasoning_tokens
        usage_state["tool_input_tokens"] = tool_input_tokens
        usage_state["total_tokens"] = total_tokens

    def accumulate_usage_candidate(
        self,
        *,
        usage_state: dict[str, Any],
        usage_sources: dict[str, dict[str, int]],
        source_id: str,
        usage_candidate: dict[str, Any],
    ) -> bool:
        source_key = source_id.strip()
        if not source_key:
            return False

        has_signal = False
        for field in self.usage_numeric_fields():
            if self.as_int(usage_candidate.get(field, 0)) > 0:
                has_signal = True
                break
        if not has_signal:
            return False

        previous = usage_sources.get(
            source_key, {field: 0 for field in self.usage_numeric_fields()}
        )

        changed = False
        for field in self.usage_numeric_fields():
            prior_value = self.as_int(previous.get(field, 0))
            incoming_value = self.as_int(usage_candidate.get(field, 0))
            next_value = max(prior_value, incoming_value)
            if next_value <= prior_value:
                continue
            delta = next_value - prior_value
            usage_state[field] = self.as_int(usage_state.get(field, 0)) + delta
            previous[field] = next_value
            changed = True

        if changed:
            usage_sources[source_key] = previous
            self.normalize_aggregated_usage(usage_state)
        self.merge_usage_identity(usage_state, usage_candidate)
        return changed

    def accumulate_usage_from_messages(
        self,
        *,
        usage_state: dict[str, Any],
        usage_sources: dict[str, dict[str, int]],
        messages: list[Any],
        source_prefix: str,
        config: AppConfig | None,
        fallback_model: str | None = None,
        fallback_base_url: str | None = None,
        fallback_provider: str | None = None,
        source_offset: int = 0,
    ) -> bool:
        changed = False
        for index, message in enumerate(messages):
            candidate = self.extract_usage_from_message(
                config=config,
                message=message,
                fallback_model=fallback_model,
                fallback_base_url=fallback_base_url,
                fallback_provider=fallback_provider,
            )
            source_id = str(getattr(message, "id", "")).strip()
            if source_id:
                source_key = f"{source_prefix}:{source_id}"
            else:
                source_key = f"{source_prefix}:{source_offset + index}"
            changed = (
                self.accumulate_usage_candidate(
                    usage_state=usage_state,
                    usage_sources=usage_sources,
                    source_id=source_key,
                    usage_candidate=candidate,
                )
                or changed
            )
        return changed

    def usage_signature(self, usage_state: dict[str, Any]) -> str:
        parts = [str(usage_state.get(field, "")) for field in self.usage_numeric_fields()]
        parts.extend(
            [
                str(usage_state.get("provider", "")),
                str(usage_state.get("model", "")),
                str(usage_state.get("model_source", "")),
                str(usage_state.get("usage_source", "")),
            ]
        )
        return "|".join(parts)

    def extract_usage_from_message(
        self,
        *,
        config: AppConfig | None,
        message: Any,
        fallback_model: str | None = None,
        fallback_base_url: str | None = None,
        fallback_provider: str | None = None,
    ) -> dict[str, Any]:
        if config is None:
            return {}
        model_fallback = (fallback_model or "").strip()
        if not model_fallback:
            default_profile = config.llm_profiles.get(config.default_llm_profile)
            model_fallback = default_profile.model if default_profile is not None else ""
        return extract_usage_from_message(
            message=message,
            fallback_model=model_fallback,
            fallback_base_url=fallback_base_url or "",
            explicit_provider=fallback_provider,
        )

    def record_usage(
        self,
        *,
        usage: dict[str, Any],
        run_id: str,
        session_id: str,
        trigger_type: str,
        agent_id: str,
        usage_store: UsageStore,
    ) -> dict[str, Any]:
        provider = str(usage.get("provider", "unknown")).strip() or "unknown"
        model = str(usage.get("model", "unknown")).strip() or "unknown"
        usage_cost = calculate_cost_breakdown(
            provider=provider,
            model=model,
            input_tokens=self.as_int(usage.get("input_tokens", 0)),
            input_uncached_tokens=self.as_int(usage.get("input_uncached_tokens", 0)),
            input_cache_read_tokens=self.as_int(
                usage.get("input_cache_read_tokens", 0)
            ),
            input_cache_write_tokens_5m=self.as_int(
                usage.get("input_cache_write_tokens_5m", 0)
            ),
            input_cache_write_tokens_1h=self.as_int(
                usage.get("input_cache_write_tokens_1h", 0)
            ),
            input_cache_write_tokens_unknown=self.as_int(
                usage.get("input_cache_write_tokens_unknown", 0)
            ),
            output_tokens=self.as_int(usage.get("output_tokens", 0)),
        )
        enriched = {
            "schema_version": 2,
            "agent_id": agent_id,
            "provider": provider,
            "model": model,
            "trigger_type": trigger_type,
            "run_id": run_id,
            "session_id": session_id,
            "model_source": str(usage.get("model_source", "unknown")),
            "usage_source": str(usage.get("usage_source", "unknown")),
            "input_tokens": self.as_int(usage.get("input_tokens", 0)),
            "input_uncached_tokens": self.as_int(usage.get("input_uncached_tokens", 0)),
            "input_cache_read_tokens": self.as_int(
                usage.get("input_cache_read_tokens", 0)
            ),
            "input_cache_write_tokens_5m": self.as_int(
                usage.get("input_cache_write_tokens_5m", 0)
            ),
            "input_cache_write_tokens_1h": self.as_int(
                usage.get("input_cache_write_tokens_1h", 0)
            ),
            "input_cache_write_tokens_unknown": self.as_int(
                usage.get("input_cache_write_tokens_unknown", 0)
            ),
            "output_tokens": self.as_int(usage.get("output_tokens", 0)),
            "reasoning_tokens": self.as_int(usage.get("reasoning_tokens", 0)),
            "tool_input_tokens": self.as_int(usage.get("tool_input_tokens", 0)),
            "total_tokens": self.as_int(usage.get("total_tokens", 0)),
            "priced": bool(usage_cost.get("priced", False)),
            "cost_usd": usage_cost.get("total_cost_usd"),
            "pricing": usage_cost,
        }
        usage_store.append_record(enriched)
        return enriched
