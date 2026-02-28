from __future__ import annotations


def test_chat_non_stream_respects_first_turn_flag(client):
    session_id = client.post("/api/sessions", json={}).json()["data"]["session_id"]

    first = client.post(
        "/api/chat",
        json={"message": "hello", "session_id": session_id, "stream": False},
    )
    assert first.status_code == 200
    assert "first=1" in first.json()["data"]["content"]

    second = client.post(
        "/api/chat",
        json={"message": "again", "session_id": session_id, "stream": False},
    )
    assert second.status_code == 200
    assert "first=0" in second.json()["data"]["content"]


def test_runtime_config_endpoint_roundtrip(client):
    before = client.get("/api/config/runtime")
    assert before.status_code == 200
    payload = before.json()["data"]["config"]
    assert payload["scheduler"]["api_enabled"] is True

    payload["scheduler"]["runs_query_default_limit"] = 42
    payload["retrieval"]["storage"]["engine"] = "sqlite"
    payload["retrieval"]["storage"]["fts_prefilter_k"] = 25

    updated = client.put("/api/config/runtime", json={"config": payload})
    assert updated.status_code == 200
    assert updated.json()["data"]["config"]["scheduler"]["runs_query_default_limit"] == 42
    assert updated.json()["data"]["config"]["retrieval"]["storage"]["fts_prefilter_k"] == 25


def test_tokens_session_uses_agent_effective_runtime(client):
    default_session = client.post("/api/sessions", json={}).json()["data"]["session_id"]
    created = client.post("/api/agents", json={"agent_id": "alpha"})
    assert created.status_code == 200
    alpha_session = client.post("/api/sessions?agent_id=alpha", json={}).json()["data"]["session_id"]

    toggle = client.put("/api/config/rag-mode?agent_id=alpha", json={"enabled": True})
    assert toggle.status_code == 200

    default_tokens = client.get(f"/api/tokens/session/{default_session}")
    alpha_tokens = client.get(f"/api/tokens/session/{alpha_session}?agent_id=alpha")
    assert default_tokens.status_code == 200
    assert alpha_tokens.status_code == 200

    default_system = default_tokens.json()["data"]["system_tokens"]
    alpha_system = alpha_tokens.json()["data"]["system_tokens"]
    assert alpha_system > default_system
