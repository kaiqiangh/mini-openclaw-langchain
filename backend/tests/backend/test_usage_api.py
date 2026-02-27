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
                "timestamp_ms": now_ms - 60_000,
                "model": "deepseek-chat",
                "trigger_type": "chat",
                "session_id": "s1",
                "input_tokens": 100,
                "cached_input_tokens": 20,
                "uncached_input_tokens": 80,
                "output_tokens": 50,
                "reasoning_tokens": 10,
                "total_tokens": 150,
                "estimated_cost_usd": 0.0001,
            },
            {
                "timestamp_ms": now_ms - 30_000,
                "model": "deepseek-chat",
                "trigger_type": "chat",
                "session_id": "s2",
                "input_tokens": 40,
                "cached_input_tokens": 0,
                "uncached_input_tokens": 40,
                "output_tokens": 15,
                "reasoning_tokens": 0,
                "total_tokens": 55,
                "estimated_cost_usd": 0.00002,
            },
            {
                "timestamp_ms": now_ms - 15_000,
                "model": "deepseek-chat",
                "trigger_type": "chat",
                "session_id": "s3",
                "input_tokens": "[REDACTED]",
                "cached_input_tokens": "[REDACTED]",
                "uncached_input_tokens": "[REDACTED]",
                "output_tokens": "[REDACTED]",
                "reasoning_tokens": "[REDACTED]",
                "total_tokens": "[REDACTED]",
                "estimated_cost_usd": 0.00011,
            },
        ],
    )

    records = client.get("/api/usage/records", params={"since_hours": 2, "model": "deepseek-chat", "limit": 10})
    assert records.status_code == 200
    payload = records.json()["data"]
    assert payload["count"] == 3
    assert all(item["model"] == "deepseek-chat" for item in payload["records"])
    assert all(isinstance(item["input_tokens"], int) for item in payload["records"])
    assert all(item["total_tokens"] > 0 for item in payload["records"])

    summary = client.get("/api/usage/summary", params={"since_hours": 2, "trigger_type": "chat"})
    assert summary.status_code == 200
    data = summary.json()["data"]
    assert data["totals"]["runs"] == 3
    assert data["totals"]["input_tokens"] >= 140
    assert data["totals"]["cached_input_tokens"] >= 20
    assert data["totals"]["output_tokens"] >= 65
    assert data["totals"]["total_tokens"] > 205
    assert len(data["by_model"]) == 1
