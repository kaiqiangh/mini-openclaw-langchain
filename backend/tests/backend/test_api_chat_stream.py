from __future__ import annotations

import json


def _parse_sse_events(payload: str) -> list[str]:
    events: list[str] = []
    for line in payload.splitlines():
        if line.startswith("event:"):
            events.append(line.replace("event:", "").strip())
    return events


def test_chat_sse_order_and_segment_persistence(client, api_app):
    created = client.post("/api/sessions", json={}).json()
    session_id = created["data"]["session_id"]

    response = client.post(
        "/api/chat",
        json={"message": "hello", "session_id": session_id, "stream": True},
    )
    assert response.status_code == 200

    events = _parse_sse_events(response.text)
    expected_core_order = [
        "retrieval",
        "token",
        "tool_start",
        "tool_end",
        "new_response",
        "token",
        "done",
        "title",
    ]
    idx = 0
    for event in events:
        if idx < len(expected_core_order) and event == expected_core_order[idx]:
            idx += 1
    assert idx == len(expected_core_order)
    assert "run_start" in events
    assert "agent_update" in events
    assert "reasoning" in events

    history = client.get(f"/api/sessions/{session_id}/history").json()["data"][
        "messages"
    ]
    assert len(history) == 3
    assert history[0]["role"] == "user"
    assert history[1]["role"] == "assistant"
    assert history[2]["role"] == "assistant"

    # Ensure structured message linkage audit records are persisted.
    links_file = api_app["base_dir"] / "storage" / "audit" / "message_links.jsonl"
    rows = [
        json.loads(line)
        for line in links_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(rows) >= 3
    assert any(
        row.get("role") == "assistant" and row.get("segment_index") == 1 for row in rows
    )
