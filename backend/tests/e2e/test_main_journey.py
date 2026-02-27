from __future__ import annotations


def test_main_user_journey_flow(client, api_app):
    # start session
    created = client.post("/api/sessions", json={}).json()
    session_id = created["data"]["session_id"]

    # first response
    stream = client.post(
        "/api/chat",
        json={"message": "hello", "session_id": session_id, "stream": False},
    )
    assert stream.status_code == 200
    assert stream.json()["data"]["session_id"] == session_id

    # ensure enough history and compress
    manager = api_app["session_manager"]
    manager.save_message(session_id, "user", "u2")
    manager.save_message(session_id, "assistant", "a2")
    compressed = client.post(f"/api/sessions/{session_id}/compress")
    assert compressed.status_code == 200

    # toggle rag mode
    toggled = client.put("/api/config/rag-mode", json={"enabled": True})
    assert toggled.status_code == 200
    assert toggled.json()["data"]["enabled"] is True
