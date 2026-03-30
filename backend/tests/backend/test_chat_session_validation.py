"""Tests for chat session validation — using conftest fixtures."""
import pytest


def test_chat_rejects_nonexistent_session(client):
    """Chat endpoint must not silently create sessions for nonexistent IDs."""
    response = client.post(
        "/api/v1/agents/default/chat",
        json={
            "message": "hello",
            "session_id": "totally-nonexistent-session-id-12345",
            "stream": False,
        },
    )
    assert response.status_code in (400, 404), (
        f"Expected 400/404 for nonexistent session, got {response.status_code}: {response.text[:200]}"
    )


def test_chat_accepts_existing_session(client):
    """Chat endpoint must work with a properly created session."""
    # First create a session
    create_resp = client.post(
        "/api/v1/agents/default/sessions",
        json={"title": "Test Session"},
    )
    assert create_resp.status_code == 201
    session_id = create_resp.json()["data"]["session_id"]

    # Now chat should work (non-streaming)
    response = client.post(
        "/api/v1/agents/default/chat",
        json={
            "message": "hello",
            "session_id": session_id,
            "stream": False,
        },
    )
    # Should NOT get 404 (session exists)
    # May get 500 if no LLM configured, but that's fine — session was found
    assert response.status_code != 404, "Existing session should be found"
