from __future__ import annotations

import json

from sse_starlette.sse import AppStatus


def _parse_sse_events(payload: str) -> list[str]:
    events: list[str] = []
    for line in payload.splitlines():
        if line.startswith("event:"):
            events.append(line.replace("event:", "").strip())
    return events


def test_chat_sse_order_and_segment_persistence(client, api_app):
    created = client.post("/api/v1/agents/default/sessions", json={}).json()
    session_id = created["data"]["session_id"]

    response = client.post(
        "/api/v1/agents/default/chat",
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

    history = client.get(
        f"/api/v1/agents/default/sessions/{session_id}/history"
    ).json()["data"]["messages"]
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


def test_chat_resume_same_turn_avoids_duplicate_user_message(client, api_app):
    AppStatus.should_exit = False
    if hasattr(AppStatus, "should_exit_event"):
        setattr(AppStatus, "should_exit_event", None)

    manager = api_app["agent_manager"]
    call_count = {"value": 0}

    async def scripted_stream(
        self, message: str, history: list[dict[str, object]], session_id: str, **kwargs
    ):
        _ = self, history, kwargs
        call_count["value"] += 1
        if call_count["value"] == 1:
            yield {"type": "run_start", "data": {"run_id": "run-first", "attempt": 1}}
            yield {
                "type": "error",
                "data": {
                    "error": "Recursion limit reached",
                    "code": "max_steps_reached",
                    "run_id": "run-first",
                    "attempt": 1,
                },
            }
            return
        yield {"type": "run_start", "data": {"run_id": "run-second", "attempt": 1}}
        yield {"type": "token", "data": {"content": "continued"}}
        yield {
            "type": "done",
            "data": {
                "content": f"{message}-continued",
                "session_id": session_id,
                "run_id": "run-second",
            },
        }

    manager.astream = scripted_stream.__get__(manager, type(manager))

    created = client.post("/api/v1/agents/default/sessions", json={}).json()
    session_id = created["data"]["session_id"]

    first = client.post(
        "/api/v1/agents/default/chat",
        json={"message": "hello", "session_id": session_id, "stream": True},
    )
    assert first.status_code == 200
    assert "event: error" in first.text

    resumed = client.post(
        "/api/v1/agents/default/chat",
        json={
            "message": "hello",
            "session_id": session_id,
            "stream": True,
            "resume_same_turn": True,
        },
    )
    assert resumed.status_code == 200
    assert "event: done" in resumed.text

    history = client.get(
        f"/api/v1/agents/default/sessions/{session_id}/history"
    ).json()["data"]["messages"]
    user_messages = [row for row in history if row.get("role") == "user"]
    assistant_messages = [row for row in history if row.get("role") == "assistant"]
    assert len(user_messages) == 1
    assert len(assistant_messages) == 1
