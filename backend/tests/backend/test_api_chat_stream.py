from __future__ import annotations

import json

from sse_starlette.sse import AppStatus


def _parse_sse_events(payload: str) -> list[str]:
    events: list[str] = []
    for line in payload.splitlines():
        if line.startswith("event:"):
            events.append(line.replace("event:", "").strip())
    return events


def _parse_sse_records(payload: str) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    current_event = ""
    current_data = ""
    for line in payload.splitlines():
        if not line.strip():
            if current_event:
                parsed_data: object
                if current_data.strip():
                    parsed_data = json.loads(current_data)
                else:
                    parsed_data = {}
                records.append({"event": current_event, "data": parsed_data})
            current_event = ""
            current_data = ""
            continue
        if line.startswith("event:"):
            current_event = line.replace("event:", "").strip()
        elif line.startswith("data:"):
            current_data = line.replace("data:", "", 1).strip()
    if current_event:
        records.append(
            {
                "event": current_event,
                "data": json.loads(current_data) if current_data.strip() else {},
            }
        )
    return records


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
    assert all(int(message["timestamp_ms"]) > 0 for message in history)

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
    captured_histories: list[list[tuple[str, str]]] = []

    async def scripted_stream(
        self, message: str, history: list[dict[str, object]], session_id: str, **kwargs
    ):
        _ = self, kwargs
        captured_histories.append(
            [
                (str(item.get("role", "")), str(item.get("content", "")))
                for item in history
            ]
        )
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
    session_manager = manager.get_runtime("default").session_manager
    session_manager.save_message(session_id, "user", "prior-question")
    session_manager.save_message(session_id, "assistant", "prior-answer")

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
    assert len(user_messages) == 2
    assert len(assistant_messages) == 2
    assert user_messages[0]["content"] == "prior-question"
    assert user_messages[1]["content"] == "hello"
    assert assistant_messages[0]["content"] == "prior-answer"
    assert assistant_messages[1]["content"] == "continued"
    assert all(int(message["timestamp_ms"]) > 0 for message in history)

    assert len(captured_histories) == 2
    first_call, second_call = captured_histories
    assert ("user", "prior-question") in first_call
    assert ("assistant", "prior-answer") in first_call
    assert ("user", "prior-question") in second_call
    assert ("assistant", "prior-answer") in second_call
    assert ("user", "hello") not in second_call


def test_chat_stream_hides_backend_exception_text(client, api_app):
    AppStatus.should_exit = False
    if hasattr(AppStatus, "should_exit_event"):
        setattr(AppStatus, "should_exit_event", None)

    manager = api_app["agent_manager"]

    async def failing_stream(
        self, message: str, history: list[dict[str, object]], session_id: str, **kwargs
    ):
        _ = self, message, history, session_id, kwargs
        raise RuntimeError("provider failed at /tmp/secret-config")
        yield  # pragma: no cover

    manager.astream = failing_stream.__get__(manager, type(manager))

    session_id = client.post("/api/v1/agents/default/sessions", json={}).json()["data"][
        "session_id"
    ]
    response = client.post(
        "/api/v1/agents/default/chat",
        json={"message": "hello", "session_id": session_id, "stream": True},
    )

    assert response.status_code == 200
    assert "Stream failed. Check server logs for details." in response.text
    assert "provider failed" not in response.text
    assert "/tmp/secret-config" not in response.text


def test_chat_stream_tracks_skill_usage_in_events_and_history(client, api_app):
    AppStatus.should_exit = False
    if hasattr(AppStatus, "should_exit_event"):
        setattr(AppStatus, "should_exit_event", None)

    manager = api_app["agent_manager"]

    async def scripted_stream(
        self, message: str, history: list[dict[str, object]], session_id: str, **kwargs
    ):
        _ = self, history, kwargs
        yield {"type": "run_start", "data": {"run_id": "run-skill", "attempt": 1}}
        yield {
            "type": "selected_skills",
            "data": {
                "skills": [
                    {
                        "name": "weather_helper",
                        "location": "./skills/weather_helper/SKILL.md",
                        "reason": "matched terms: weather",
                    }
                ]
            },
        }
        yield {
            "type": "tool_start",
            "data": {
                "tool": "read_files",
                "input": {"path": "skills/get_weather/SKILL.md"},
            },
        }
        yield {"type": "tool_end", "data": {"tool": "read_files", "output": "ok"}}
        yield {
            "type": "done",
            "data": {
                "content": f"{message}-done",
                "session_id": session_id,
                "run_id": "run-skill",
            },
        }

    manager.astream = scripted_stream.__get__(manager, type(manager))

    session_id = client.post("/api/v1/agents/default/sessions", json={}).json()["data"][
        "session_id"
    ]
    response = client.post(
        "/api/v1/agents/default/chat",
        json={"message": "hello", "session_id": session_id, "stream": True},
    )

    assert response.status_code == 200
    records = _parse_sse_records(response.text)
    selected_skills = next(
        record for record in records if record["event"] == "selected_skills"
    )
    assert selected_skills["data"]["skills"][0]["name"] == "weather_helper"  # type: ignore[index]
    tool_start = next(record for record in records if record["event"] == "tool_start")
    assert tool_start["data"]["skill_uses"] == ["get_weather"]  # type: ignore[index]

    history = client.get(
        f"/api/v1/agents/default/sessions/{session_id}/history"
    ).json()["data"]["messages"]
    assistant_messages = [row for row in history if row.get("role") == "assistant"]
    assert len(assistant_messages) == 1
    assert assistant_messages[0]["selected_skills"] == ["weather_helper"]
    assert assistant_messages[0]["skill_uses"] == ["get_weather"]
    assert assistant_messages[0]["tool_calls"][0]["tool"] == "read_files"
