from __future__ import annotations

import asyncio


def test_main_user_journey_flow(client, api_app):
    # start session
    created = client.post("/api/v1/agents/default/sessions", json={}).json()
    session_id = created["data"]["session_id"]

    # first response
    stream = client.post(
        "/api/v1/agents/default/chat",
        json={"message": "hello", "session_id": session_id, "stream": False},
    )
    assert stream.status_code == 200
    assert stream.json()["data"]["session_id"] == session_id

    # ensure enough history and compress
    repository = api_app["agent_manager"].get_session_repository("default")
    for role, content in [("user", "u2"), ("assistant", "a2")]:
        asyncio.run(
            repository.append_message(
                agent_id="default",
                session_id=session_id,
                role=role,
                content=content,
            )
        )
    compressed = client.post(f"/api/v1/agents/default/sessions/{session_id}/compress")
    assert compressed.status_code == 200

    # toggle rag mode
    toggled = client.put(
        "/api/v1/agents/default/config/rag-mode", json={"enabled": True}
    )
    assert toggled.status_code == 200
    assert toggled.json()["data"]["enabled"] is True
