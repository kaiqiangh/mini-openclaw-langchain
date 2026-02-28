from __future__ import annotations


def test_sessions_files_tokens_compress_and_config_contracts(client, api_app):
    created = client.post("/api/sessions", json={})
    assert created.status_code == 200
    session_id = created.json()["data"]["session_id"]

    listed = client.get("/api/sessions")
    assert listed.status_code == 200
    assert any(item["session_id"] == session_id for item in listed.json()["data"])

    renamed = client.put(f"/api/sessions/{session_id}", json={"title": "New"})
    assert renamed.status_code == 200
    assert renamed.json()["data"]["title"] == "New"

    read_file = client.get("/api/files", params={"path": "memory/MEMORY.md"})
    assert read_file.status_code == 200

    files_index = client.get("/api/files/index")
    assert files_index.status_code == 200
    assert "memory/MEMORY.md" in files_index.json()["data"]["files"]

    write_file = client.post(
        "/api/files", json={"path": "memory/NEW.md", "content": "abc"}
    )
    assert write_file.status_code == 200

    token_session = client.get(f"/api/tokens/session/{session_id}")
    assert token_session.status_code == 200
    assert token_session.json()["data"]["total_tokens"] >= 0

    token_files = client.post(
        "/api/tokens/files",
        json={"paths": ["memory/MEMORY.md", "../../etc/passwd"]},
    )
    assert token_files.status_code == 200
    assert token_files.json()["data"][1]["error"] == "invalid_path"

    rag_get = client.get("/api/config/rag-mode")
    assert rag_get.status_code == 200
    assert rag_get.json()["data"]["agent_id"] == "default"
    rag_put = client.put("/api/config/rag-mode", json={"enabled": True})
    assert rag_put.status_code == 200
    assert rag_put.json()["data"]["enabled"] is True
    assert rag_put.json()["data"]["agent_id"] == "default"

    create_other_agent = client.post("/api/agents", json={"agent_id": "agent-rag"})
    assert create_other_agent.status_code == 200

    rag_other_before = client.get(
        "/api/config/rag-mode", params={"agent_id": "agent-rag"}
    )
    assert rag_other_before.status_code == 200
    assert rag_other_before.json()["data"]["enabled"] is False
    assert rag_other_before.json()["data"]["agent_id"] == "agent-rag"

    rag_other_put = client.put(
        "/api/config/rag-mode?agent_id=agent-rag", json={"enabled": True}
    )
    assert rag_other_put.status_code == 200
    assert rag_other_put.json()["data"]["enabled"] is True
    assert rag_other_put.json()["data"]["agent_id"] == "agent-rag"

    rag_default_after = client.get("/api/config/rag-mode")
    assert rag_default_after.status_code == 200
    assert rag_default_after.json()["data"]["enabled"] is True

    tracing_get = client.get("/api/config/tracing")
    assert tracing_get.status_code == 200
    assert tracing_get.json()["data"]["provider"] == "langsmith"
    assert tracing_get.json()["data"]["config_key"] == "OBS_TRACING_ENABLED"

    tracing_put = client.put("/api/config/tracing", json={"enabled": True})
    assert tracing_put.status_code == 200
    assert tracing_put.json()["data"]["enabled"] is True

    tracing_after = client.get("/api/config/tracing")
    assert tracing_after.status_code == 200
    assert tracing_after.json()["data"]["enabled"] is True

    # compression error envelope for <4 messages
    compress_small = client.post(f"/api/sessions/{session_id}/compress")
    assert compress_small.status_code == 400
    assert compress_small.json()["error"]["code"] == "invalid_state"

    gen_title = client.post(f"/api/sessions/{session_id}/generate-title")
    assert gen_title.status_code == 400
    assert gen_title.json()["error"]["code"] == "invalid_state"

    # add enough messages and compress successfully
    manager = api_app["session_manager"]
    manager.save_message(session_id, "user", "u1")
    manager.save_message(session_id, "assistant", "a1")
    manager.save_message(session_id, "user", "u2")
    manager.save_message(session_id, "assistant", "a2")

    compress_ok = client.post(f"/api/sessions/{session_id}/compress")
    assert compress_ok.status_code == 200
    assert compress_ok.json()["data"]["archived_count"] >= 4

    gen_title = client.post(f"/api/sessions/{session_id}/generate-title")
    assert gen_title.status_code == 200
    assert isinstance(gen_title.json()["data"]["title"], str)

    deleted = client.delete(f"/api/sessions/{session_id}")
    assert deleted.status_code == 200
    assert deleted.json()["data"]["deleted"] is True


def test_archive_restore_and_delete_archived_session(client):
    created = client.post("/api/sessions", json={}).json()
    session_id = created["data"]["session_id"]

    archived = client.post(f"/api/sessions/{session_id}/archive")
    assert archived.status_code == 200
    assert archived.json()["data"]["archived"] is True

    active_list = client.get("/api/sessions")
    assert active_list.status_code == 200
    assert all(item["session_id"] != session_id for item in active_list.json()["data"])

    archived_list = client.get("/api/sessions", params={"scope": "archived"})
    assert archived_list.status_code == 200
    assert any(
        item["session_id"] == session_id and item["archived"] is True
        for item in archived_list.json()["data"]
    )

    restored = client.post(f"/api/sessions/{session_id}/restore")
    assert restored.status_code == 200
    assert restored.json()["data"]["restored"] is True

    archived_again = client.post(f"/api/sessions/{session_id}/archive")
    assert archived_again.status_code == 200

    deleted = client.delete(f"/api/sessions/{session_id}", params={"archived": "true"})
    assert deleted.status_code == 200
    assert deleted.json()["data"]["archived"] is True


def test_agents_endpoint_and_session_isolation(client):
    created_agent = client.post("/api/agents", json={"agent_id": "agent-b"})
    assert created_agent.status_code == 200
    assert created_agent.json()["data"]["agent_id"] == "agent-b"

    default_session = client.post("/api/sessions", json={}).json()["data"]["session_id"]
    other_session = client.post("/api/sessions?agent_id=agent-b", json={}).json()[
        "data"
    ]["session_id"]

    default_list = client.get("/api/sessions").json()["data"]
    other_list = client.get("/api/sessions?agent_id=agent-b").json()["data"]

    assert any(item["session_id"] == default_session for item in default_list)
    assert all(item["session_id"] != other_session for item in default_list)
    assert any(item["session_id"] == other_session for item in other_list)

    default_files = client.get("/api/files/index").json()["data"]["files"]
    other_files = client.get("/api/files/index?agent_id=agent-b").json()["data"][
        "files"
    ]
    assert "memory/MEMORY.md" in default_files
    assert "memory/MEMORY.md" in other_files
