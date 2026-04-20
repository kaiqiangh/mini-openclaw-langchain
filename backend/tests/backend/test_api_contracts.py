from __future__ import annotations

import asyncio

from graph.compaction import CompactionPipeline
from langchain_core.messages import HumanMessage


def test_sessions_files_tokens_compress_and_config_contracts(client, api_app):
    created = client.post("/api/v1/agents/default/sessions", json={})
    assert created.status_code == 201
    assert "Location" in created.headers
    session_id = created.json()["data"]["session_id"]

    listed = client.get("/api/v1/agents/default/sessions")
    assert listed.status_code == 200
    assert any(item["session_id"] == session_id for item in listed.json()["data"])

    renamed = client.put(
        f"/api/v1/agents/default/sessions/{session_id}", json={"title": "New"}
    )
    assert renamed.status_code == 200
    assert renamed.json()["data"]["title"] == "New"

    read_file = client.get(
        "/api/v1/agents/default/files", params={"path": "memory/MEMORY.md"}
    )
    assert read_file.status_code == 200

    files_index = client.get("/api/v1/agents/default/files/index")
    assert files_index.status_code == 200
    assert "memory/MEMORY.md" in files_index.json()["data"]["files"]

    write_file = client.post(
        "/api/v1/agents/default/files", json={"path": "memory/NEW.md", "content": "abc"}
    )
    assert write_file.status_code == 200

    token_session = client.get(f"/api/v1/agents/default/tokens/session/{session_id}")
    assert token_session.status_code == 200
    assert token_session.json()["data"]["total_tokens"] >= 0

    token_files = client.post(
        "/api/v1/agents/default/tokens/files",
        json={"paths": ["memory/MEMORY.md", "../../etc/passwd"]},
    )
    assert token_files.status_code == 200
    assert token_files.json()["data"][1]["error"] == "invalid_path"

    rag_get = client.get("/api/v1/agents/default/config/rag-mode")
    assert rag_get.status_code == 200
    assert rag_get.json()["data"]["agent_id"] == "default"
    rag_put = client.put(
        "/api/v1/agents/default/config/rag-mode", json={"enabled": True}
    )
    assert rag_put.status_code == 200
    assert rag_put.json()["data"]["enabled"] is True
    assert rag_put.json()["data"]["agent_id"] == "default"

    create_other_agent = client.post("/api/v1/agents", json={"agent_id": "agent-rag"})
    assert create_other_agent.status_code == 201
    assert "Location" in create_other_agent.headers

    rag_other_before = client.get("/api/v1/agents/agent-rag/config/rag-mode")
    assert rag_other_before.status_code == 200
    assert rag_other_before.json()["data"]["enabled"] is False
    assert rag_other_before.json()["data"]["agent_id"] == "agent-rag"

    rag_other_put = client.put(
        "/api/v1/agents/agent-rag/config/rag-mode", json={"enabled": True}
    )
    assert rag_other_put.status_code == 200
    assert rag_other_put.json()["data"]["enabled"] is True
    assert rag_other_put.json()["data"]["agent_id"] == "agent-rag"

    rag_default_after = client.get("/api/v1/agents/default/config/rag-mode")
    assert rag_default_after.status_code == 200
    assert rag_default_after.json()["data"]["enabled"] is True

    tracing_get = client.get("/api/v1/config/tracing")
    assert tracing_get.status_code == 200
    assert tracing_get.json()["data"]["provider"] == "langsmith"
    assert tracing_get.json()["data"]["config_key"] == "OBS_TRACING_ENABLED"

    tracing_put = client.put("/api/v1/config/tracing", json={"enabled": True})
    assert tracing_put.status_code == 200
    assert tracing_put.json()["data"]["enabled"] is True

    tracing_put_false = client.put("/api/v1/config/tracing", json={"enabled": False})
    assert tracing_put_false.status_code == 200
    assert tracing_put_false.json()["data"]["enabled"] is False

    tracing_state_path = api_app["base_dir"] / "storage" / "runtime_state.json"
    assert tracing_state_path.exists()

    tracing_after = client.get("/api/v1/config/tracing")
    assert tracing_after.status_code == 200
    assert tracing_after.json()["data"]["enabled"] is False

    # compression error envelope for <4 messages
    compress_small = client.post(
        f"/api/v1/agents/default/sessions/{session_id}/compress"
    )
    assert compress_small.status_code == 400
    assert compress_small.json()["error"]["code"] == "invalid_state"

    gen_title = client.post(
        f"/api/v1/agents/default/sessions/{session_id}/generate-title"
    )
    assert gen_title.status_code == 400
    assert gen_title.json()["error"]["code"] == "invalid_state"

    # add enough messages and compress successfully
    repository = api_app["agent_manager"].get_session_repository("default")
    for role, content in [
        ("user", "u1"),
        ("assistant", "a1"),
        ("user", "u2"),
        ("assistant", "a2"),
    ]:
        asyncio.run(
            repository.append_message(
                agent_id="default",
                session_id=session_id,
                role=role,
                content=content,
            )
        )

    compress_ok = client.post(f"/api/v1/agents/default/sessions/{session_id}/compress")
    assert compress_ok.status_code == 200
    assert compress_ok.json()["data"]["archived_count"] >= 4

    gen_title = client.post(
        f"/api/v1/agents/default/sessions/{session_id}/generate-title"
    )
    assert gen_title.status_code == 200
    assert isinstance(gen_title.json()["data"]["title"], str)

    deleted = client.delete(f"/api/v1/agents/default/sessions/{session_id}")
    assert deleted.status_code == 204
    assert deleted.content == b""


def test_archive_restore_and_delete_archived_session(client):
    created = client.post("/api/v1/agents/default/sessions", json={}).json()
    session_id = created["data"]["session_id"]

    archived = client.post(f"/api/v1/agents/default/sessions/{session_id}/archive")
    assert archived.status_code == 200
    assert archived.json()["data"]["archived"] is True

    active_list = client.get("/api/v1/agents/default/sessions")
    assert active_list.status_code == 200
    assert all(item["session_id"] != session_id for item in active_list.json()["data"])

    archived_list = client.get(
        "/api/v1/agents/default/sessions", params={"scope": "archived"}
    )
    assert archived_list.status_code == 200
    assert any(
        item["session_id"] == session_id and item["archived"] is True
        for item in archived_list.json()["data"]
    )

    restored = client.post(f"/api/v1/agents/default/sessions/{session_id}/restore")
    assert restored.status_code == 200
    assert restored.json()["data"]["restored"] is True

    archived_again = client.post(
        f"/api/v1/agents/default/sessions/{session_id}/archive"
    )
    assert archived_again.status_code == 200

    deleted = client.delete(
        f"/api/v1/agents/default/sessions/{session_id}", params={"archived": "true"}
    )
    assert deleted.status_code == 204
    assert deleted.content == b""


def test_missing_session_reads_return_404_without_creating_files(client, api_app):
    session_id = "missing-session"
    runtime = api_app["agent_manager"].get_runtime("default")
    session_path = runtime.session_manager.sessions_dir / f"{session_id}.json"
    assert not session_path.exists()

    history = client.get(f"/api/v1/agents/default/sessions/{session_id}/history")
    messages = client.get(f"/api/v1/agents/default/sessions/{session_id}/messages")

    assert history.status_code == 404
    assert history.json()["error"]["code"] == "not_found"
    assert messages.status_code == 404
    assert messages.json()["error"]["code"] == "not_found"
    assert not session_path.exists()


def test_agents_endpoint_and_session_isolation(client):
    created_agent = client.post("/api/v1/agents", json={"agent_id": "agent-b"})
    assert created_agent.status_code == 201
    assert "Location" in created_agent.headers
    assert created_agent.json()["data"]["agent_id"] == "agent-b"

    default_session = client.post("/api/v1/agents/default/sessions", json={}).json()[
        "data"
    ]["session_id"]
    other_session = client.post("/api/v1/agents/agent-b/sessions", json={}).json()[
        "data"
    ]["session_id"]

    default_list = client.get("/api/v1/agents/default/sessions").json()["data"]
    other_list = client.get("/api/v1/agents/agent-b/sessions").json()["data"]

    assert any(item["session_id"] == default_session for item in default_list)
    assert all(item["session_id"] != other_session for item in default_list)
    assert any(item["session_id"] == other_session for item in other_list)

    default_files = client.get("/api/v1/agents/default/files/index").json()["data"][
        "files"
    ]
    other_files = client.get("/api/v1/agents/agent-b/files/index").json()["data"][
        "files"
    ]
    assert "memory/MEMORY.md" in default_files
    assert "memory/MEMORY.md" in other_files


def test_internal_sessions_are_hidden_and_rejected_by_public_session_endpoints(
    client, api_app
):
    public_session_id = client.post("/api/v1/agents/default/sessions", json={}).json()[
        "data"
    ]["session_id"]
    runtime = api_app["agent_manager"].get_runtime("default")

    asyncio.run(
        runtime.session_manager.create_session(
            "delegate-child-1",
            title="Delegate Child",
            hidden=True,
            internal=True,
            metadata={
                "session_kind": "delegate_child",
                "parent_session_id": public_session_id,
                "delegate_id": "del_test1234",
            },
        )
    )

    listed = client.get("/api/v1/agents/default/sessions")
    assert listed.status_code == 200
    assert all(
        item["session_id"] != "delegate-child-1"
        for item in listed.json()["data"]
    )

    history = client.get(
        "/api/v1/agents/default/sessions/delegate-child-1/history"
    )
    rename = client.put(
        "/api/v1/agents/default/sessions/delegate-child-1",
        json={"title": "Renamed Child"},
    )
    delete = client.delete("/api/v1/agents/default/sessions/delegate-child-1")

    assert history.status_code == 404
    assert rename.status_code == 404
    assert delete.status_code == 404


def test_delegate_endpoints_use_raw_session_scoped_contract(client, api_app):
    session_id = client.post("/api/v1/agents/default/sessions", json={}).json()[
        "data"
    ]["session_id"]
    registry = api_app["agent_manager"].runtime_services.delegate_registry
    registration = registry.register(
        agent_id="default",
        parent_session_id=session_id,
        task="Summarize the latest session state",
        role="researcher",
        allowed_tools=["read_files"],
        blocked_tools=["agents_list"],
        timeout_seconds=60,
    )
    registry.mark_completed(
        registration["delegate_id"],
        {
            "summary": "Delegate finished successfully.",
            "steps": 2,
            "tools_used": ["read_files"],
            "token_usage": {"input_tokens": 10, "output_tokens": 4},
        },
    )

    listed = client.get(f"/api/v1/agents/default/sessions/{session_id}/delegates")
    assert listed.status_code == 200
    listed_payload = listed.json()
    assert set(listed_payload.keys()) == {"delegates"}
    assert len(listed_payload["delegates"]) == 1
    assert listed_payload["delegates"][0]["delegate_id"] == registration["delegate_id"]

    detail = client.get(
        f"/api/v1/agents/default/sessions/{session_id}/delegates/{registration['delegate_id']}"
    )
    assert detail.status_code == 200
    detail_payload = detail.json()
    assert "data" not in detail_payload
    assert detail_payload["delegate_id"] == registration["delegate_id"]
    assert detail_payload["parent_session_id"] == session_id
    assert detail_payload["allowed_tools"] == ["read_files"]
    assert detail_payload["blocked_tools"] == ["agents_list"]
    assert detail_payload["tools_used"] == ["read_files"]
    assert detail_payload["result_summary"] == "Delegate finished successfully."
    assert detail_payload["result_file"].endswith("/result_summary.md")


def test_delegate_detail_exposes_timeout_terminal_contract(client, api_app):
    session_id = client.post("/api/v1/agents/default/sessions", json={}).json()[
        "data"
    ]["session_id"]
    registry = api_app["agent_manager"].runtime_services.delegate_registry
    registration = registry.register(
        agent_id="default",
        parent_session_id=session_id,
        task="Summarize the latest session state",
        role="researcher",
        allowed_tools=["read_files"],
        blocked_tools=["agents_list"],
        timeout_seconds=7,
    )
    registry.mark_timeout(registration["delegate_id"])

    detail = client.get(
        f"/api/v1/agents/default/sessions/{session_id}/delegates/{registration['delegate_id']}"
    )
    assert detail.status_code == 200
    detail_payload = detail.json()
    assert "data" not in detail_payload
    assert detail_payload["delegate_id"] == registration["delegate_id"]
    assert detail_payload["status"] == "timeout"
    assert detail_payload["allowed_tools"] == ["read_files"]
    assert detail_payload["blocked_tools"] == ["agents_list"]
    assert detail_payload["error_message"] == "Sub-agent exceeded timeout (7s)"
    assert detail_payload["result_file"].endswith("/result_summary.md")


def test_checkpoint_endpoints_enforce_exact_session_ownership(client, api_app):
    session_a = client.post("/api/v1/agents/default/sessions", json={}).json()["data"][
        "session_id"
    ]
    session_b = client.post("/api/v1/agents/default/sessions", json={}).json()["data"][
        "session_id"
    ]
    runtime = api_app["agent_manager"].get_runtime("default")
    pipeline = CompactionPipeline(
        model_name="gpt-4o",
        checkpoint_dir=runtime.root_dir / "storage" / "checkpoints",
    )

    owned_checkpoint = asyncio.run(
        pipeline.create_checkpoint(
            [HumanMessage(content="owned")],
            run_id="owned-a",
            step=1,
            agent_id="default",
            session_id=session_a,
        )
    )
    other_checkpoint = asyncio.run(
        pipeline.create_checkpoint(
            [HumanMessage(content="other")],
            run_id="owned-b",
            step=2,
            agent_id="default",
            session_id=session_b,
        )
    )
    legacy_checkpoint = asyncio.run(
        pipeline.create_checkpoint(
            [HumanMessage(content="legacy")],
            run_id="legacy",
            step=3,
        )
    )

    listed = client.get(f"/api/v1/agents/default/sessions/{session_a}/checkpoints")
    assert listed.status_code == 200
    checkpoint_ids = [row["checkpoint_id"] for row in listed.json()["data"]]
    assert checkpoint_ids == [owned_checkpoint]

    other_rewind = client.post(
        f"/api/v1/agents/default/sessions/{session_a}/rewind",
        json={"checkpoint_id": other_checkpoint},
    )
    legacy_rewind = client.post(
        f"/api/v1/agents/default/sessions/{session_a}/rewind",
        json={"checkpoint_id": legacy_checkpoint},
    )
    owned_rewind = client.post(
        f"/api/v1/agents/default/sessions/{session_a}/rewind",
        json={"checkpoint_id": owned_checkpoint},
    )

    assert other_rewind.status_code == 404
    assert legacy_rewind.status_code == 404
    assert owned_rewind.status_code == 200
    assert owned_rewind.json()["data"]["checkpoint_id"] == owned_checkpoint
    assert owned_rewind.json()["data"]["message_count"] == 1


def test_cron_sessions_use_job_name_in_session_lists(client):
    created_job = client.post(
        "/api/v1/agents/default/scheduler/cron/jobs",
        json={
            "name": "crypto-daily-brief",
            "schedule_type": "every",
            "schedule": "60",
            "prompt": "summarize market action",
            "enabled": True,
        },
    )
    assert created_job.status_code == 201
    job_id = created_job.json()["data"]["job"]["id"]

    run_now = client.post(f"/api/v1/agents/default/scheduler/cron/jobs/{job_id}/run")
    assert run_now.status_code == 200

    listed = client.get("/api/v1/agents/default/sessions")
    assert listed.status_code == 200
    sessions = listed.json()["data"]
    cron_session = next(
        item for item in sessions if item["session_id"] == f"__cron__:{job_id}"
    )
    assert cron_session["title"] == "crypto-daily-brief"
