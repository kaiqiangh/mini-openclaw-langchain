from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from graph.agent import AgentManager
from graph.runtime_types import (
    BlockingDelegateRef,
    ResolvedDelegateResult,
    RuntimeRequest,
)
from graph.skill_selector import SelectedSkill
from graph.session_manager import LegacySessionStateError


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True) + "\n", encoding="utf-8")


def _seed_base(base_dir: Path) -> None:
    for rel in ("workspace", "memory", "knowledge", "skills", "storage", "workspaces"):
        (base_dir / rel).mkdir(parents=True, exist_ok=True)
    for name in (
        "AGENTS.md",
        "SOUL.md",
        "IDENTITY.md",
        "USER.md",
        "HEARTBEAT.md",
        "BOOTSTRAP.md",
    ):
        (base_dir / "workspace" / name).write_text(f"# {name}\n", encoding="utf-8")
    (base_dir / "memory" / "MEMORY.md").write_text("# MEMORY\nhello world\n", encoding="utf-8")
    _write_json(
        base_dir / "config.json",
        {"llm_defaults": {"default": "openai", "fallbacks": []}},
    )


def test_graph_state_wrappers_create_sqlite_checkpoint(tmp_path: Path):
    _seed_base(tmp_path)
    manager = AgentManager()
    manager.initialize(tmp_path)

    asyncio.run(
        manager.update_graph_state(
            session_id="session-1",
            values={
                "messages": [{"role": "user", "content": "hello", "timestamp_ms": 1}],
                "compressed_context": "summary",
            },
        )
    )

    state = asyncio.run(manager.get_graph_state(session_id="session-1"))
    history = asyncio.run(manager.get_graph_state_history(session_id="session-1"))
    checkpoint_db = (
        manager.get_runtime("default").root_dir
        / "storage"
        / "langgraph_checkpoints.sqlite"
    )

    assert checkpoint_db.exists()
    assert state["messages"][0]["content"] == "hello"
    assert state["compressed_context"] == "summary"
    assert history


def test_graph_state_wrappers_round_trip_blocking_delegate_runtime_types(tmp_path: Path):
    _seed_base(tmp_path)
    manager = AgentManager()
    manager.initialize(tmp_path)

    asyncio.run(
        manager.update_graph_state(
            session_id="delegate-session",
            values={
                "messages": [{"role": "user", "content": "delegate", "timestamp_ms": 1}],
                "pending_blocking_delegates": [
                    BlockingDelegateRef(
                        delegate_id="del_1234",
                        role="researcher",
                        task="Summarize memory",
                        sub_session_id="sub_1234",
                    )
                ],
                "resolved_delegate_results": [
                    ResolvedDelegateResult(
                        delegate_id="del_1234",
                        role="researcher",
                        task="Summarize memory",
                        status="timeout",
                        result_summary="",
                        tools_used=[],
                        duration_ms=120_000,
                        error_message="Sub-agent exceeded timeout (120s)",
                    )
                ],
                "pending_delegate_result_injection": [
                    ResolvedDelegateResult(
                        delegate_id="del_1234",
                        role="researcher",
                        task="Summarize memory",
                        status="timeout",
                        result_summary="",
                        tools_used=[],
                        duration_ms=120_000,
                        error_message="Sub-agent exceeded timeout (120s)",
                    )
                ],
                "selected_skill_items": [
                    SelectedSkill(
                        name="memory-helper",
                        location="./skills/memory-helper/SKILL.md",
                        description="memory helper",
                        reason="matched terms: memory",
                        score=12,
                    )
                ],
                "delegate_waiting": False,
            },
        )
    )

    reloaded = AgentManager()
    reloaded.initialize(tmp_path)

    state = asyncio.run(reloaded.get_graph_state(session_id="delegate-session"))
    history = asyncio.run(reloaded.get_graph_state_history(session_id="delegate-session"))

    assert state["pending_blocking_delegates"][0].delegate_id == "del_1234"
    assert state["resolved_delegate_results"][0].status == "timeout"
    assert (
        state["pending_delegate_result_injection"][0].error_message
        == "Sub-agent exceeded timeout (120s)"
    )
    assert state["selected_skill_items"][0].name == "memory-helper"
    assert history


def test_checkpoint_repository_rejects_legacy_session_json_messages(tmp_path: Path):
    _seed_base(tmp_path)
    manager = AgentManager()
    manager.initialize(tmp_path)

    session_manager = manager.get_runtime("default").session_manager
    asyncio.run(session_manager.create_session("legacy-session", title="Legacy"))
    session = asyncio.run(session_manager.load_session("legacy-session"))
    session["messages"] = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "second"},
    ]
    session["compressed_context"] = "older summary"
    asyncio.run(session_manager.save_session("legacy-session", session))

    with pytest.raises(
        LegacySessionStateError,
        match="unsupported legacy conversation messages",
    ):
        asyncio.run(
            manager.get_session_repository("default").load_snapshot(
                agent_id="default",
                session_id="legacy-session",
                include_live=False,
            )
        )


def test_prepare_runtime_request_uses_checkpoint_history_for_resume(tmp_path: Path):
    _seed_base(tmp_path)
    manager = AgentManager()
    manager.initialize(tmp_path)

    repository = manager.get_session_repository("default")
    asyncio.run(
        repository.append_message(
            agent_id="default",
            session_id="resume-session",
            role="user",
            content="hello",
        )
    )

    prepared = asyncio.run(
        repository.prepare_runtime_request(
            RuntimeRequest(
                message="hello",
                history=[],
                session_id="resume-session",
                agent_id="default",
                resume_same_turn=True,
            )
        )
    )
    state = asyncio.run(manager.get_graph_state(session_id="resume-session"))

    assert prepared.resume_same_turn is True
    assert prepared.history == []
    assert [row["content"] for row in state["messages"]] == ["hello"]


def test_delete_session_removes_checkpoint_thread(tmp_path: Path):
    _seed_base(tmp_path)
    manager = AgentManager()
    manager.initialize(tmp_path)

    session_manager = manager.get_runtime("default").session_manager
    asyncio.run(session_manager.create_session("delete-session", title="Delete Me"))
    asyncio.run(
        manager.update_graph_state(
            session_id="delete-session",
            values={
                "messages": [{"role": "user", "content": "bye", "timestamp_ms": 1}],
            },
        )
    )

    deleted = asyncio.run(
        manager.get_session_repository("default").delete_session(
            agent_id="default",
            session_id="delete-session",
        )
    )
    state = asyncio.run(manager.get_graph_state(session_id="delete-session"))

    assert deleted is True
    assert state == {}
    assert not (session_manager.sessions_dir / "delete-session.json").exists()


def test_repository_repairs_broken_tool_loop_state_on_access(tmp_path: Path):
    _seed_base(tmp_path)
    manager = AgentManager()
    manager.initialize(tmp_path)

    session_manager = manager.get_runtime("default").session_manager
    asyncio.run(session_manager.create_session("broken-session", title="Broken"))
    asyncio.run(
        manager.update_graph_state(
            session_id="broken-session",
            values={
                "messages": [
                    {"role": "user", "content": "current time", "timestamp_ms": 1}
                ],
                "model_messages": [
                    AIMessage(
                        content="I'll check the current time for you.",
                        tool_calls=[
                            {
                                "name": "terminal",
                                "args": {"command": "date"},
                                "id": "call-1",
                                "type": "tool_call",
                            }
                        ],
                    ),
                    ToolMessage(
                        content='{"ok": true, "data": {"stdout": "Thu Mar 12 22:09:29 GMT 2026"}}',
                        tool_call_id="call-1",
                    ),
                ],
                "fallback_final_text": "I'll check the current time for you.",
                "loop_count": 51,
                "error": {
                    "error": "Recursion limit of 50 reached without hitting a stop condition.",
                    "code": "max_steps_reached",
                    "run_id": "run-broken",
                    "attempt": 1,
                },
            },
        )
    )

    repository = manager.get_session_repository("default")
    prepared = asyncio.run(
        repository.prepare_runtime_request(
            RuntimeRequest(
                message="current time",
                history=[],
                session_id="broken-session",
                agent_id="default",
                resume_same_turn=True,
            )
        )
    )
    repaired = asyncio.run(manager.get_graph_state(session_id="broken-session"))

    assert prepared.resume_same_turn is True
    assert prepared.history == []
    assert [row["content"] for row in repaired["messages"]] == ["current time"]
    assert repaired["model_messages"] == []
    assert repaired["pending_tool_calls"] == []
    assert repaired["fallback_final_text"] == ""
    assert repaired["error"] is None
