from __future__ import annotations


def test_chat_non_stream_respects_first_turn_flag(client):
    session_id = client.post("/api/v1/agents/default/sessions", json={}).json()["data"][
        "session_id"
    ]

    first = client.post(
        "/api/v1/agents/default/chat",
        json={"message": "hello", "session_id": session_id, "stream": False},
    )
    assert first.status_code == 200
    assert "first=1" in first.json()["data"]["content"]

    second = client.post(
        "/api/v1/agents/default/chat",
        json={"message": "again", "session_id": session_id, "stream": False},
    )
    assert second.status_code == 200
    assert "first=0" in second.json()["data"]["content"]


def test_runtime_config_endpoint_roundtrip(client):
    before = client.get("/api/v1/agents/default/config/runtime")
    assert before.status_code == 200
    payload = before.json()["data"]["config"]
    assert payload["scheduler"]["api_enabled"] is True
    cron_tools = payload["autonomous_tools"]["cron_enabled_tools"]
    assert "web_search" in cron_tools
    assert "web_fetch" in cron_tools

    payload["scheduler"]["runs_query_default_limit"] = 42
    payload["retrieval"]["storage"]["engine"] = "sqlite"
    payload["retrieval"]["storage"]["fts_prefilter_k"] = 25

    updated = client.put(
        "/api/v1/agents/default/config/runtime", json={"config": payload}
    )
    assert updated.status_code == 200
    assert (
        updated.json()["data"]["config"]["scheduler"]["runs_query_default_limit"] == 42
    )
    assert (
        updated.json()["data"]["config"]["retrieval"]["storage"]["fts_prefilter_k"]
        == 25
    )


def test_tokens_session_uses_agent_effective_runtime(client):
    default_session = client.post("/api/v1/agents/default/sessions", json={}).json()[
        "data"
    ]["session_id"]
    created = client.post("/api/v1/agents", json={"agent_id": "alpha"})
    assert created.status_code == 201
    alpha_session = client.post("/api/v1/agents/alpha/sessions", json={}).json()[
        "data"
    ]["session_id"]

    toggle = client.put("/api/v1/agents/alpha/config/rag-mode", json={"enabled": True})
    assert toggle.status_code == 200

    default_tokens = client.get(
        f"/api/v1/agents/default/tokens/session/{default_session}"
    )
    alpha_tokens = client.get(f"/api/v1/agents/alpha/tokens/session/{alpha_session}")
    assert default_tokens.status_code == 200
    assert alpha_tokens.status_code == 200

    default_system = default_tokens.json()["data"]["system_tokens"]
    alpha_system = alpha_tokens.json()["data"]["system_tokens"]
    assert alpha_system > default_system
