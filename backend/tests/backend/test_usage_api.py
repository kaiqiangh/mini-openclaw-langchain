from __future__ import annotations

import json
import time


def _write_usage_rows(base_dir, rows):
    usage_dir = base_dir / "storage" / "usage"
    usage_dir.mkdir(parents=True, exist_ok=True)
    target = usage_dir / "llm_usage.jsonl"
    target.write_text(
        "\n".join(json.dumps(row, ensure_ascii=True) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_usage_summary_and_records_filters(client, api_app):
    now_ms = int(time.time() * 1000)
    _write_usage_rows(
        api_app["base_dir"],
        [
            {
                "schema_version": 2,
                "timestamp_ms": now_ms - 60_000,
                "provider": "deepseek",
                "model": "deepseek-chat",
                "trigger_type": "chat",
                "session_id": "s1",
                "run_id": "r1",
                "input_tokens": 120,
                "input_uncached_tokens": 100,
                "input_cache_read_tokens": 20,
                "input_cache_write_tokens_5m": 0,
                "input_cache_write_tokens_1h": 0,
                "input_cache_write_tokens_unknown": 0,
                "output_tokens": 50,
                "reasoning_tokens": 10,
                "tool_input_tokens": 0,
                "total_tokens": 170,
                "priced": True,
                "cost_usd": 0.0001,
                "pricing": {
                    "priced": True,
                    "total_cost_usd": 0.0001,
                },
            },
            {
                "schema_version": 2,
                "timestamp_ms": now_ms - 30_000,
                "provider": "deepseek",
                "model": "deepseek-chat",
                "trigger_type": "chat",
                "session_id": "s2",
                "run_id": "r2",
                "input_tokens": 40,
                "input_uncached_tokens": 40,
                "input_cache_read_tokens": 0,
                "input_cache_write_tokens_5m": 0,
                "input_cache_write_tokens_1h": 0,
                "input_cache_write_tokens_unknown": 0,
                "output_tokens": 15,
                "reasoning_tokens": 0,
                "tool_input_tokens": 0,
                "total_tokens": 55,
                "priced": True,
                "cost_usd": 0.00002,
                "pricing": {
                    "priced": True,
                    "total_cost_usd": 0.00002,
                },
            },
            {
                "schema_version": 2,
                "timestamp_ms": now_ms - 15_000,
                "provider": "google",
                "model": "gemini-2.5-flash",
                "trigger_type": "chat",
                "session_id": "s3",
                "run_id": "r3",
                "input_tokens": 90,
                "input_uncached_tokens": 90,
                "input_cache_read_tokens": 0,
                "input_cache_write_tokens_5m": 0,
                "input_cache_write_tokens_1h": 0,
                "input_cache_write_tokens_unknown": 0,
                "output_tokens": 25,
                "reasoning_tokens": 0,
                "tool_input_tokens": 0,
                "total_tokens": 115,
                "priced": False,
                "cost_usd": None,
                "pricing": {
                    "priced": False,
                    "total_cost_usd": None,
                    "unpriced_reason": "model_not_in_catalog",
                },
            },
        ],
    )

    records = client.get(
        "/api/usage/records",
        params={"since_hours": 2, "provider": "deepseek", "limit": 10},
    )
    assert records.status_code == 200
    payload = records.json()["data"]
    assert payload["count"] == 2
    assert all(item["provider"] == "deepseek" for item in payload["records"])
    assert all(isinstance(item["input_tokens"], int) for item in payload["records"])
    assert all(item["total_tokens"] > 0 for item in payload["records"])

    summary = client.get(
        "/api/usage/summary", params={"since_hours": 2, "trigger_type": "chat"}
    )
    assert summary.status_code == 200
    data = summary.json()["data"]
    assert data["totals"]["runs"] == 3
    assert data["totals"]["priced_runs"] == 2
    assert data["totals"]["unpriced_runs"] == 1
    assert data["totals"]["input_tokens"] >= 250
    assert data["totals"]["input_cache_read_tokens"] >= 20
    assert data["totals"]["output_tokens"] >= 90
    assert data["totals"]["total_tokens"] >= 340
    assert len(data["by_provider_model"]) == 2
    assert len(data["by_provider"]) == 2
