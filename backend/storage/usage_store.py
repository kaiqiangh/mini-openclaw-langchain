from __future__ import annotations

import json
import math
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class UsageQuery:
    since_hours: int = 24
    provider: str | None = None
    model: str | None = None
    trigger_type: str | None = None
    session_id: str | None = None
    limit: int = 500


class UsageStore:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.usage_dir = base_dir / "storage" / "usage"
        self.usage_dir.mkdir(parents=True, exist_ok=True)
        self.records_file = self.usage_dir / "llm_usage.jsonl"
        self._lock = threading.Lock()

    def append_record(self, payload: dict[str, Any]) -> None:
        row = dict(payload)
        row.setdefault("timestamp_ms", int(time.time() * 1000))
        with self._lock:
            with self.records_file.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _iter_records(self) -> list[dict[str, Any]]:
        if not self.records_file.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in self.records_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            if isinstance(row, dict):
                rows.append(row)
        return rows

    @staticmethod
    def _coerce_int(value: Any) -> int:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            if math.isfinite(value):
                return int(value)
            return 0
        if isinstance(value, str):
            raw = value.strip().replace(",", "")
            if not raw:
                return 0
            try:
                return int(raw)
            except Exception:
                try:
                    return int(float(raw))
                except Exception:
                    return 0
        return 0

    @staticmethod
    def _coerce_float(value: Any) -> float | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return float(value)
        if isinstance(value, (int, float)):
            cast = float(value)
            return cast if math.isfinite(cast) else None
        if isinstance(value, str):
            raw = value.strip().replace(",", "")
            if not raw:
                return None
            try:
                cast = float(raw)
            except Exception:
                return None
            return cast if math.isfinite(cast) else None
        return None

    @staticmethod
    def _coerce_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "y", "on"}:
                return True
            if normalized in {"0", "false", "no", "n", "off", ""}:
                return False
        return False

    def _normalize_record(self, row: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(row)

        provider = str(normalized.get("provider", "unknown")).strip().lower() or "unknown"
        model = str(normalized.get("model", "unknown")).strip() or "unknown"
        trigger_type = str(normalized.get("trigger_type", "")).strip().lower()
        session_id = str(normalized.get("session_id", "")).strip()
        run_id = str(normalized.get("run_id", "")).strip()

        input_tokens = max(0, self._coerce_int(normalized.get("input_tokens", 0)))
        input_uncached_tokens = max(
            0, self._coerce_int(normalized.get("input_uncached_tokens", 0))
        )
        input_cache_read_tokens = max(
            0, self._coerce_int(normalized.get("input_cache_read_tokens", 0))
        )
        input_cache_write_tokens_5m = max(
            0, self._coerce_int(normalized.get("input_cache_write_tokens_5m", 0))
        )
        input_cache_write_tokens_1h = max(
            0, self._coerce_int(normalized.get("input_cache_write_tokens_1h", 0))
        )
        input_cache_write_tokens_unknown = max(
            0,
            self._coerce_int(normalized.get("input_cache_write_tokens_unknown", 0)),
        )

        output_tokens = max(0, self._coerce_int(normalized.get("output_tokens", 0)))
        reasoning_tokens = max(
            0, self._coerce_int(normalized.get("reasoning_tokens", 0))
        )
        tool_input_tokens = max(
            0, self._coerce_int(normalized.get("tool_input_tokens", 0))
        )
        total_tokens = max(0, self._coerce_int(normalized.get("total_tokens", 0)))

        cache_write_total = (
            input_cache_write_tokens_5m
            + input_cache_write_tokens_1h
            + input_cache_write_tokens_unknown
        )

        if input_tokens <= 0 and (
            input_uncached_tokens > 0
            or input_cache_read_tokens > 0
            or cache_write_total > 0
        ):
            input_tokens = (
                input_uncached_tokens + input_cache_read_tokens + cache_write_total
            )

        if input_uncached_tokens <= 0 and input_tokens > 0:
            input_uncached_tokens = max(
                0,
                input_tokens - input_cache_read_tokens - cache_write_total,
            )

        if input_uncached_tokens > input_tokens:
            input_uncached_tokens = input_tokens

        if total_tokens <= 0:
            total_tokens = input_tokens + output_tokens + tool_input_tokens
        else:
            total_tokens = max(total_tokens, input_tokens + output_tokens + tool_input_tokens)

        pricing = normalized.get("pricing")
        pricing_payload = pricing if isinstance(pricing, dict) else {}

        cost_usd = self._coerce_float(normalized.get("cost_usd"))
        if cost_usd is None:
            cost_usd = self._coerce_float(pricing_payload.get("total_cost_usd"))

        priced = self._coerce_bool(normalized.get("priced"))
        if "priced" not in normalized:
            priced = self._coerce_bool(pricing_payload.get("priced"))

        if not priced:
            cost_usd = None

        timestamp_ms = max(0, self._coerce_int(normalized.get("timestamp_ms", 0)))

        return {
            "schema_version": self._coerce_int(normalized.get("schema_version", 2))
            or 2,
            "timestamp_ms": timestamp_ms,
            "agent_id": str(normalized.get("agent_id", "default")).strip() or "default",
            "provider": provider,
            "model": model,
            "model_source": str(normalized.get("model_source", "unknown")).strip()
            or "unknown",
            "usage_source": str(normalized.get("usage_source", "unknown")).strip()
            or "unknown",
            "trigger_type": trigger_type,
            "run_id": run_id,
            "session_id": session_id,
            "input_tokens": input_tokens,
            "input_uncached_tokens": input_uncached_tokens,
            "input_cache_read_tokens": input_cache_read_tokens,
            "input_cache_write_tokens_5m": input_cache_write_tokens_5m,
            "input_cache_write_tokens_1h": input_cache_write_tokens_1h,
            "input_cache_write_tokens_unknown": input_cache_write_tokens_unknown,
            "output_tokens": output_tokens,
            "reasoning_tokens": reasoning_tokens,
            "tool_input_tokens": tool_input_tokens,
            "total_tokens": total_tokens,
            "priced": priced,
            "cost_usd": round(cost_usd, 8) if cost_usd is not None else None,
            "pricing": pricing_payload,
        }

    def query_records(self, query: UsageQuery) -> list[dict[str, Any]]:
        now_ms = int(time.time() * 1000)
        min_ts = now_ms - max(1, int(query.since_hours)) * 3600 * 1000
        provider_filter = query.provider.strip().lower() if query.provider else None
        model_filter = query.model.strip().lower() if query.model else None
        trigger_filter = (
            query.trigger_type.strip().lower() if query.trigger_type else None
        )
        session_filter = query.session_id.strip() if query.session_id else None

        filtered: list[dict[str, Any]] = []
        for raw in self._iter_records():
            row = self._normalize_record(raw)
            if int(row.get("timestamp_ms", 0)) < min_ts:
                continue
            provider = str(row.get("provider", "")).lower()
            model = str(row.get("model", "")).lower()
            trigger = str(row.get("trigger_type", "")).lower()
            session_id = str(row.get("session_id", "")).strip()

            if provider_filter and provider != provider_filter:
                continue
            if model_filter and model != model_filter:
                continue
            if trigger_filter and trigger != trigger_filter:
                continue
            if session_filter and session_id != session_filter:
                continue
            filtered.append(row)

        filtered.sort(key=lambda item: int(item.get("timestamp_ms", 0)), reverse=True)
        return filtered[: max(1, int(query.limit))]

    def summarize(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        normalized_records = [self._normalize_record(item) for item in records]

        totals: dict[str, Any] = {
            "runs": len(normalized_records),
            "priced_runs": 0,
            "unpriced_runs": 0,
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
            "cost_usd": 0.0,
        }

        by_provider_model: dict[str, dict[str, Any]] = {}
        by_provider: dict[str, dict[str, Any]] = {}

        for row in normalized_records:
            provider = str(row.get("provider", "unknown"))
            model = str(row.get("model", "unknown"))
            key = f"{provider}|{model}"

            model_bucket = by_provider_model.setdefault(
                key,
                {
                    "provider": provider,
                    "model": model,
                    "runs": 0,
                    "priced_runs": 0,
                    "unpriced_runs": 0,
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
                    "cost_usd": 0.0,
                },
            )

            provider_bucket = by_provider.setdefault(
                provider,
                {
                    "provider": provider,
                    "runs": 0,
                    "priced_runs": 0,
                    "unpriced_runs": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                    "cost_usd": 0.0,
                },
            )

            numeric_fields = (
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

            model_bucket["runs"] += 1
            provider_bucket["runs"] += 1
            for field in numeric_fields:
                value = self._coerce_int(row.get(field, 0))
                model_bucket[field] += value
                totals[field] += value

            provider_bucket["input_tokens"] += self._coerce_int(row.get("input_tokens", 0))
            provider_bucket["output_tokens"] += self._coerce_int(row.get("output_tokens", 0))
            provider_bucket["total_tokens"] += self._coerce_int(row.get("total_tokens", 0))

            cost_value = self._coerce_float(row.get("cost_usd"))
            is_priced = bool(row.get("priced", False)) and cost_value is not None
            if is_priced:
                model_bucket["priced_runs"] += 1
                provider_bucket["priced_runs"] += 1
                totals["priced_runs"] += 1
                model_bucket["cost_usd"] = round(
                    model_bucket["cost_usd"] + float(cost_value), 8
                )
                provider_bucket["cost_usd"] = round(
                    provider_bucket["cost_usd"] + float(cost_value), 8
                )
                totals["cost_usd"] = round(totals["cost_usd"] + float(cost_value), 8)
            else:
                model_bucket["unpriced_runs"] += 1
                provider_bucket["unpriced_runs"] += 1
                totals["unpriced_runs"] += 1

        provider_model_rows = sorted(
            by_provider_model.values(),
            key=lambda item: (
                float(item.get("cost_usd", 0.0)),
                int(item.get("total_tokens", 0)),
            ),
            reverse=True,
        )
        provider_rows = sorted(
            by_provider.values(),
            key=lambda item: (
                float(item.get("cost_usd", 0.0)),
                int(item.get("total_tokens", 0)),
            ),
            reverse=True,
        )

        return {
            "totals": totals,
            "by_provider_model": provider_model_rows,
            "by_provider": provider_rows,
        }
