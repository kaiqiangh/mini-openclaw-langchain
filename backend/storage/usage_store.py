from __future__ import annotations

import json
import math
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from usage.pricing import resolve_model_pricing


@dataclass
class UsageQuery:
    since_hours: int = 24
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
    def _int(value: Any) -> int:
        try:
            return int(value)
        except Exception:
            return 0

    @staticmethod
    def _float(value: Any) -> float:
        try:
            return float(value)
        except Exception:
            return 0.0

    @staticmethod
    def _coerce_int(value: Any) -> tuple[int, bool]:
        if isinstance(value, bool):
            return int(value), True
        if isinstance(value, int):
            return value, True
        if isinstance(value, float):
            if math.isfinite(value):
                return int(value), True
            return 0, False
        if isinstance(value, str):
            raw = value.strip().replace(",", "")
            if not raw:
                return 0, False
            try:
                return int(raw), True
            except Exception:
                try:
                    return int(float(raw)), True
                except Exception:
                    return 0, False
        return 0, False

    @staticmethod
    def _clamp(value: float, low: float, high: float) -> float:
        return max(low, min(high, value))

    def _build_model_profiles(self, rows: list[dict[str, Any]]) -> tuple[dict[str, dict[str, float]], dict[str, float]]:
        accum: dict[str, dict[str, float]] = {}
        global_accum = {"samples": 0.0, "output_ratio": 0.0, "cached_ratio": 0.0, "reasoning_ratio": 0.0}

        for row in rows:
            model_key = str(row.get("model", "unknown")).strip().lower() or "unknown"

            input_tokens, input_ok = self._coerce_int(row.get("input_tokens", 0))
            cached_tokens, cached_ok = self._coerce_int(row.get("cached_input_tokens", 0))
            output_tokens, output_ok = self._coerce_int(row.get("output_tokens", 0))
            reasoning_tokens, reasoning_ok = self._coerce_int(row.get("reasoning_tokens", 0))
            total_tokens, total_ok = self._coerce_int(row.get("total_tokens", 0))

            input_tokens = max(0, input_tokens)
            cached_tokens = max(0, cached_tokens)
            output_tokens = max(0, output_tokens)
            reasoning_tokens = max(0, reasoning_tokens)
            total_tokens = max(0, total_tokens)

            if not total_ok and input_ok and output_ok:
                total_tokens = input_tokens + output_tokens
                total_ok = True

            if not total_ok or total_tokens <= 0:
                continue

            if not input_ok:
                input_tokens = max(0, total_tokens - output_tokens)
            if not output_ok:
                output_tokens = max(0, total_tokens - input_tokens)
            if not cached_ok:
                cached_tokens = 0
            if not reasoning_ok:
                reasoning_tokens = 0

            cached_tokens = min(cached_tokens, input_tokens)
            reasoning_tokens = min(reasoning_tokens, output_tokens)
            total_tokens = max(total_tokens, input_tokens + output_tokens)
            if total_tokens <= 0:
                continue

            output_ratio = self._clamp(output_tokens / total_tokens, 0.0, 1.0)
            cached_ratio = self._clamp((cached_tokens / input_tokens) if input_tokens > 0 else 0.0, 0.0, 1.0)
            reasoning_ratio = self._clamp((reasoning_tokens / output_tokens) if output_tokens > 0 else 0.0, 0.0, 1.0)

            bucket = accum.setdefault(
                model_key,
                {"samples": 0.0, "output_ratio": 0.0, "cached_ratio": 0.0, "reasoning_ratio": 0.0},
            )
            bucket["samples"] += 1.0
            bucket["output_ratio"] += output_ratio
            bucket["cached_ratio"] += cached_ratio
            bucket["reasoning_ratio"] += reasoning_ratio

            global_accum["samples"] += 1.0
            global_accum["output_ratio"] += output_ratio
            global_accum["cached_ratio"] += cached_ratio
            global_accum["reasoning_ratio"] += reasoning_ratio

        profiles: dict[str, dict[str, float]] = {}
        for key, bucket in accum.items():
            samples = max(1.0, bucket["samples"])
            profiles[key] = {
                "output_ratio": bucket["output_ratio"] / samples,
                "cached_ratio": bucket["cached_ratio"] / samples,
                "reasoning_ratio": bucket["reasoning_ratio"] / samples,
            }

        global_samples = max(1.0, global_accum["samples"])
        global_profile = {
            "output_ratio": global_accum["output_ratio"] / global_samples if global_accum["samples"] > 0 else 0.35,
            "cached_ratio": global_accum["cached_ratio"] / global_samples if global_accum["samples"] > 0 else 0.0,
            "reasoning_ratio": global_accum["reasoning_ratio"] / global_samples if global_accum["samples"] > 0 else 0.0,
        }
        return profiles, global_profile

    def _infer_tokens_from_cost(
        self,
        *,
        model: str,
        estimated_cost_usd: float,
        profile: dict[str, float] | None,
    ) -> dict[str, int] | None:
        pricing = resolve_model_pricing(model)
        if pricing is None or estimated_cost_usd <= 0:
            return None

        profile = profile or {}
        output_ratio = self._clamp(float(profile.get("output_ratio", 0.35)), 0.05, 0.95)
        cached_ratio = self._clamp(float(profile.get("cached_ratio", 0.0)), 0.0, 0.95)
        reasoning_ratio = self._clamp(float(profile.get("reasoning_ratio", 0.0)), 0.0, 0.95)

        blended_input_cost = (
            (1.0 - cached_ratio) * pricing.input_usd_per_1m + cached_ratio * pricing.cached_input_usd_per_1m
        )
        blended_cost_per_1m = (1.0 - output_ratio) * blended_input_cost + output_ratio * pricing.output_usd_per_1m
        if blended_cost_per_1m <= 0:
            return None

        total_tokens = max(1, int(round((estimated_cost_usd * 1_000_000.0) / blended_cost_per_1m)))
        output_tokens = int(round(total_tokens * output_ratio))
        output_tokens = max(0, min(output_tokens, total_tokens))
        input_tokens = max(0, total_tokens - output_tokens)
        cached_input_tokens = max(0, min(int(round(input_tokens * cached_ratio)), input_tokens))
        uncached_input_tokens = max(0, input_tokens - cached_input_tokens)
        reasoning_tokens = max(0, min(int(round(output_tokens * reasoning_ratio)), output_tokens))
        return {
            "input_tokens": input_tokens,
            "cached_input_tokens": cached_input_tokens,
            "uncached_input_tokens": uncached_input_tokens,
            "output_tokens": output_tokens,
            "reasoning_tokens": reasoning_tokens,
            "total_tokens": total_tokens,
        }

    def _normalize_record(
        self,
        row: dict[str, Any],
        *,
        model_profiles: dict[str, dict[str, float]],
        global_profile: dict[str, float],
    ) -> dict[str, Any]:
        normalized = dict(row)
        model = str(normalized.get("model", "unknown")).strip() or "unknown"
        model_key = model.lower()

        input_tokens, input_ok = self._coerce_int(normalized.get("input_tokens", 0))
        cached_tokens, cached_ok = self._coerce_int(normalized.get("cached_input_tokens", 0))
        uncached_tokens, uncached_ok = self._coerce_int(normalized.get("uncached_input_tokens", 0))
        output_tokens, output_ok = self._coerce_int(normalized.get("output_tokens", 0))
        reasoning_tokens, reasoning_ok = self._coerce_int(normalized.get("reasoning_tokens", 0))
        total_tokens, total_ok = self._coerce_int(normalized.get("total_tokens", 0))

        input_tokens = max(0, input_tokens)
        cached_tokens = max(0, cached_tokens)
        uncached_tokens = max(0, uncached_tokens)
        output_tokens = max(0, output_tokens)
        reasoning_tokens = max(0, reasoning_tokens)
        total_tokens = max(0, total_tokens)

        if not total_ok and input_ok and output_ok:
            total_tokens = input_tokens + output_tokens
            total_ok = True
        if not input_ok and total_ok and output_ok:
            input_tokens = max(0, total_tokens - output_tokens)
            input_ok = True
        if not output_ok and total_ok and input_ok:
            output_tokens = max(0, total_tokens - input_tokens)
            output_ok = True
        if not cached_ok:
            cached_tokens = 0
            cached_ok = True
        cached_tokens = min(cached_tokens, input_tokens)
        if not uncached_ok:
            uncached_tokens = max(0, input_tokens - cached_tokens)
            uncached_ok = True
        if not reasoning_ok:
            reasoning_tokens = 0
            reasoning_ok = True
        reasoning_tokens = min(reasoning_tokens, output_tokens)
        if total_tokens <= 0 and (input_tokens > 0 or output_tokens > 0):
            total_tokens = input_tokens + output_tokens
            total_ok = True
        if total_tokens < input_tokens + output_tokens:
            total_tokens = input_tokens + output_tokens

        estimated_cost_usd = self._float(normalized.get("estimated_cost_usd", 0.0))
        needs_inference = (input_tokens <= 0 and output_tokens <= 0 and total_tokens <= 0) and estimated_cost_usd > 0.0
        if needs_inference:
            inferred = self._infer_tokens_from_cost(
                model=model,
                estimated_cost_usd=estimated_cost_usd,
                profile=model_profiles.get(model_key, global_profile),
            )
            if inferred is not None:
                input_tokens = inferred["input_tokens"]
                cached_tokens = inferred["cached_input_tokens"]
                uncached_tokens = inferred["uncached_input_tokens"]
                output_tokens = inferred["output_tokens"]
                reasoning_tokens = inferred["reasoning_tokens"]
                total_tokens = inferred["total_tokens"]
                normalized["token_estimation"] = "inferred_from_cost"

        cached_tokens = min(cached_tokens, input_tokens)
        uncached_tokens = max(0, input_tokens - cached_tokens)
        reasoning_tokens = min(reasoning_tokens, output_tokens)
        if total_tokens <= 0 and (input_tokens > 0 or output_tokens > 0):
            total_tokens = input_tokens + output_tokens
        total_tokens = max(total_tokens, input_tokens + output_tokens)

        normalized["input_tokens"] = input_tokens
        normalized["cached_input_tokens"] = cached_tokens
        normalized["uncached_input_tokens"] = uncached_tokens
        normalized["output_tokens"] = output_tokens
        normalized["reasoning_tokens"] = reasoning_tokens
        normalized["total_tokens"] = total_tokens
        normalized["estimated_cost_usd"] = estimated_cost_usd
        return normalized

    def query_records(self, query: UsageQuery) -> list[dict[str, Any]]:
        now_ms = int(time.time() * 1000)
        min_ts = now_ms - max(1, int(query.since_hours)) * 3600 * 1000
        model_filter = query.model.strip().lower() if query.model else None
        trigger_filter = query.trigger_type.strip().lower() if query.trigger_type else None
        session_filter = query.session_id.strip() if query.session_id else None

        filtered: list[dict[str, Any]] = []
        for row in self._iter_records():
            ts = int(row.get("timestamp_ms", 0))
            if ts < min_ts:
                continue
            model = str(row.get("model", "")).strip().lower()
            if model_filter and model != model_filter:
                continue
            trigger = str(row.get("trigger_type", "")).strip().lower()
            if trigger_filter and trigger != trigger_filter:
                continue
            session_id = str(row.get("session_id", "")).strip()
            if session_filter and session_id != session_filter:
                continue
            filtered.append(row)

        model_profiles, global_profile = self._build_model_profiles(filtered)
        normalized_rows = [
            self._normalize_record(item, model_profiles=model_profiles, global_profile=global_profile) for item in filtered
        ]
        normalized_rows.sort(key=lambda item: int(item.get("timestamp_ms", 0)), reverse=True)
        return normalized_rows[: max(1, int(query.limit))]

    def summarize(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        model_profiles, global_profile = self._build_model_profiles(records)
        normalized_records = [
            self._normalize_record(item, model_profiles=model_profiles, global_profile=global_profile) for item in records
        ]

        totals = {
            "runs": len(normalized_records),
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "uncached_input_tokens": 0,
            "output_tokens": 0,
            "reasoning_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
        }

        by_model: dict[str, dict[str, Any]] = {}
        for row in normalized_records:
            model = str(row.get("model", "unknown")).strip() or "unknown"
            block = by_model.setdefault(
                model,
                {
                    "model": model,
                    "runs": 0,
                    "input_tokens": 0,
                    "cached_input_tokens": 0,
                    "uncached_input_tokens": 0,
                    "output_tokens": 0,
                    "reasoning_tokens": 0,
                    "total_tokens": 0,
                    "estimated_cost_usd": 0.0,
                },
            )
            block["runs"] += 1
            for key in (
                "input_tokens",
                "cached_input_tokens",
                "uncached_input_tokens",
                "output_tokens",
                "reasoning_tokens",
                "total_tokens",
            ):
                value = self._int(row.get(key, 0))
                block[key] += value
                totals[key] += value

            cost = self._float(row.get("estimated_cost_usd", 0.0))
            block["estimated_cost_usd"] = round(block["estimated_cost_usd"] + cost, 8)
            totals["estimated_cost_usd"] = round(totals["estimated_cost_usd"] + cost, 8)

        model_rows = sorted(
            by_model.values(),
            key=lambda item: (float(item.get("estimated_cost_usd", 0.0)), int(item.get("total_tokens", 0))),
            reverse=True,
        )
        return {"totals": totals, "by_model": model_rows}
