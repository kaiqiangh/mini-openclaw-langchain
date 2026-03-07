from __future__ import annotations

import base64
import json
import time


def _append_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=True) + "\n")


def test_trace_events_list_normalizes_and_filters_persisted_sources(client, api_app):
    now_ms = int(time.time() * 1000)
    base_dir = api_app["base_dir"]

    _append_jsonl(
        base_dir / "storage" / "audit" / "steps.jsonl",
        [
          {
              "schema": "audit.step.v1",
              "run_id": "run-audit-tool",
              "session_id": "session-alpha",
              "trigger_type": "chat",
              "event": "tool_start",
              "details": {"tool": "read_files", "input": "{'path': 'memory/MEMORY.md'}"},
              "timestamp_ms": now_ms - 20_000,
          },
          {
              "schema": "audit.step.v1",
              "run_id": "run-audit-llm",
              "session_id": "session-alpha",
              "trigger_type": "chat",
              "event": "llm_end",
              "details": {"generation_count": 1},
              "timestamp_ms": now_ms - 10_000,
          },
        ],
    )
    _append_jsonl(
        base_dir / "storage" / "runs_events.jsonl",
        [
          {
              "run_id": "run-audit-tool",
              "session_id": "session-alpha",
              "trigger_type": "chat",
              "event": "tool_start",
              "tool": "read_files",
              "input": "{'path': 'memory/MEMORY.md'}",
              "timestamp_ms": now_ms - 20_000,
          },
          {
              "run_id": "run-events-error",
              "session_id": "session-beta",
              "trigger_type": "heartbeat",
              "event": "llm_error",
              "error": "provider timeout",
              "timestamp_ms": now_ms - 5_000,
          },
        ],
    )

    response = client.get(
        "/api/v1/agents/default/traces/events",
        params={"window": "24h", "limit": 10},
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["agent_id"] == "default"
    assert payload["total"] == 3
    assert payload["next_cursor"] is None
    assert payload["summary"]["total_matches"] == 3
    assert payload["summary"]["by_event"]["tool_start"] == 1
    assert payload["summary"]["by_event"]["llm_end"] == 1
    assert payload["summary"]["by_event"]["llm_error"] == 1

    rows = payload["events"]
    assert rows[0]["run_id"] == "run-events-error"
    assert rows[0]["source"] == "runs.events"
    assert rows[0]["summary"].startswith("provider timeout")
    assert rows[1]["run_id"] == "run-audit-llm"
    assert rows[1]["source"] == "audit.steps"
    assert rows[2]["run_id"] == "run-audit-tool"
    assert rows[2]["source"] == "audit.steps"

    filtered = client.get(
        "/api/v1/agents/default/traces/events",
        params={
            "window": "24h",
            "event": "tool_start",
            "run_id": "run-audit-tool",
            "session_id": "session-alpha",
            "trigger": "chat",
            "q": "memory",
        },
    )
    assert filtered.status_code == 200
    filtered_payload = filtered.json()["data"]
    assert filtered_payload["total"] == 1
    assert filtered_payload["events"][0]["event"] == "tool_start"
    assert filtered_payload["events"][0]["summary"].lower().count("memory") >= 1


def test_trace_events_support_cursor_pagination_and_detail_lookup(client, api_app):
    now_ms = int(time.time() * 1000)
    base_dir = api_app["base_dir"]

    _append_jsonl(
        base_dir / "storage" / "audit" / "steps.jsonl",
        [
            {
                "schema": "audit.step.v1",
                "run_id": "run-1",
                "session_id": "session-1",
                "trigger_type": "chat",
                "event": "llm_start",
                "details": {"model": "ChatOpenAI", "prompt_count": 1},
                "timestamp_ms": now_ms - 30_000,
            },
            {
                "schema": "audit.step.v1",
                "run_id": "run-2",
                "session_id": "session-2",
                "trigger_type": "chat",
                "event": "llm_end",
                "details": {"generation_count": 1},
                "timestamp_ms": now_ms - 20_000,
            },
            {
                "schema": "audit.step.v1",
                "run_id": "run-3",
                "session_id": "session-3",
                "trigger_type": "cron",
                "event": "tool_end",
                "details": {"output": "ok"},
                "timestamp_ms": now_ms - 10_000,
            },
        ],
    )

    first = client.get(
        "/api/v1/agents/default/traces/events",
        params={"window": "24h", "limit": 2},
    )
    assert first.status_code == 200
    first_payload = first.json()["data"]
    assert [row["run_id"] for row in first_payload["events"]] == ["run-3", "run-2"]
    assert isinstance(first_payload["next_cursor"], str)

    second = client.get(
        "/api/v1/agents/default/traces/events",
        params={
            "window": "24h",
            "limit": 2,
            "cursor": first_payload["next_cursor"],
        },
    )
    assert second.status_code == 200
    second_payload = second.json()["data"]
    assert [row["run_id"] for row in second_payload["events"]] == ["run-1"]

    event_id = first_payload["events"][0]["event_id"]
    detail = client.get(f"/api/v1/agents/default/traces/events/{event_id}")
    assert detail.status_code == 200
    detail_payload = detail.json()["data"]
    assert detail_payload["event_id"] == event_id
    assert detail_payload["run_id"] == "run-3"
    assert detail_payload["details"]["output"] == "ok"

    missing = client.get("/api/v1/agents/default/traces/events/missing-event")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"


def test_trace_events_preserve_missing_run_and_session_ids(client, api_app):
    now_ms = int(time.time() * 1000)
    base_dir = api_app["base_dir"]

    _append_jsonl(
        base_dir / "storage" / "audit" / "steps.jsonl",
        [
            {
                "schema": "audit.step.v1",
                "run_id": None,
                "session_id": None,
                "trigger_type": "chat",
                "event": "llm_end",
                "details": {"generation_count": 1},
                "timestamp_ms": now_ms - 1_000,
            },
        ],
    )

    response = client.get(
        "/api/v1/agents/default/traces/events",
        params={"window": "24h", "limit": 10},
    )

    assert response.status_code == 200
    payload = response.json()["data"]["events"][0]
    assert payload["run_id"] is None
    assert payload["session_id"] is None


def test_trace_events_reject_cursor_payloads_that_are_not_objects(client, api_app):
    now_ms = int(time.time() * 1000)
    base_dir = api_app["base_dir"]

    _append_jsonl(
        base_dir / "storage" / "audit" / "steps.jsonl",
        [
            {
                "schema": "audit.step.v1",
                "run_id": "run-1",
                "session_id": "session-1",
                "trigger_type": "chat",
                "event": "llm_start",
                "details": {"model": "ChatOpenAI", "prompt_count": 1},
                "timestamp_ms": now_ms - 1_000,
            },
        ],
    )

    cursor = base64.urlsafe_b64encode(json.dumps([]).encode("utf-8")).decode("ascii")
    response = client.get(
        "/api/v1/agents/default/traces/events",
        params={"window": "24h", "limit": 10, "cursor": cursor},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
