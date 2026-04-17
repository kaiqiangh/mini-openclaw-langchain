import json
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from config import DelegationConfig, RuntimeConfig
from tools.base import ToolContext
from tools.delegate_registry import DelegateRegistry
from tools.delegate_tool import build_delegate_tool


def _ctx(
    root: Path,
    session: str = "parent_session",
    *,
    agent_id: str = "alpha",
) -> ToolContext:
    return ToolContext(
        workspace_root=root,
        trigger_type="chat",
        session_id=session,
        run_id="run_1",
        agent_id=agent_id,
    )


def _runtime_with_delegation(scopes: dict[str, list[str]] | None = None):
    runtime = SimpleNamespace(
        root_dir=None,
        audit_store=None,
        session_manager=SimpleNamespace(create_session=AsyncMock()),
        runtime_config=RuntimeConfig(
            delegation=DelegationConfig(
                allowed_tool_scopes=scopes
                or {
                    "researcher": ["web_search", "fetch_url", "read_files"],
                    "writer": ["read_files", "apply_patch"],
                }
            )
        ),
    )
    return runtime


def test_delegate_tool_name(tmp_path: Path):
    registry = DelegateRegistry(base_dir=tmp_path)
    am = MagicMock()
    am.get_runtime.return_value = _runtime_with_delegation()
    tool = build_delegate_tool(agent_manager=am, registry=registry, base_dir=tmp_path, context=_ctx(tmp_path))
    assert tool.name == "delegate"


def test_rejects_empty_task(tmp_path: Path):
    registry = DelegateRegistry(base_dir=tmp_path)
    am = MagicMock()
    am.get_runtime.return_value = _runtime_with_delegation()
    tool = build_delegate_tool(agent_manager=am, registry=registry, base_dir=tmp_path, context=_ctx(tmp_path))
    result = tool.func(task="", role="researcher", allowed_tools=["web_search"])
    data = json.loads(result)
    assert "error" in data


def test_uses_role_scope_when_allowed_tools_empty(tmp_path: Path):
    registry = DelegateRegistry(base_dir=tmp_path)
    am = MagicMock()
    am.get_runtime.return_value = _runtime_with_delegation()
    tool = build_delegate_tool(agent_manager=am, registry=registry, base_dir=tmp_path, context=_ctx(tmp_path))
    result = tool.func(task="Do something", role="researcher", allowed_tools=[])
    data = json.loads(result)
    assert data["status"] == "running"
    state = registry.get_status(data["delegate_id"])
    assert state is not None
    assert state.allowed_tools == ["web_search", "fetch_url", "read_files"]


def test_rejects_delegate_in_allowed(tmp_path: Path):
    registry = DelegateRegistry(base_dir=tmp_path)
    am = MagicMock()
    am.get_runtime.return_value = _runtime_with_delegation()
    tool = build_delegate_tool(agent_manager=am, registry=registry, base_dir=tmp_path, context=_ctx(tmp_path))
    result = tool.func(task="Task", role="researcher", allowed_tools=["delegate"])
    data = json.loads(result)
    assert "error" in data


def test_rejects_allowed_tools_outside_role_scope(tmp_path: Path):
    registry = DelegateRegistry(base_dir=tmp_path)
    am = MagicMock()
    am.get_runtime.return_value = _runtime_with_delegation()
    tool = build_delegate_tool(
        agent_manager=am,
        registry=registry,
        base_dir=tmp_path,
        context=_ctx(tmp_path),
    )
    result = tool.func(
        task="Task",
        role="researcher",
        allowed_tools=["web_search", "apply_patch"],
    )
    data = json.loads(result)
    assert "error" in data
    assert "subset" in data["error"]


def test_launches_successfully(tmp_path: Path):
    registry = DelegateRegistry(base_dir=tmp_path)
    am = MagicMock()
    am.get_runtime.return_value = _runtime_with_delegation()
    tool = build_delegate_tool(agent_manager=am, registry=registry, base_dir=tmp_path, context=_ctx(tmp_path))
    result = tool.func(task="Find REST APIs", role="researcher", allowed_tools=["web_search", "fetch_url"])
    data = json.loads(result)
    assert data["status"] == "running"
    assert "delegate_id" in data
    assert "session_id" in data
    assert registry.get_status(data["delegate_id"]).status == "running"


def test_rejects_task_too_long(tmp_path: Path):
    registry = DelegateRegistry(base_dir=tmp_path)
    am = MagicMock()
    am.get_runtime.return_value = _runtime_with_delegation()
    tool = build_delegate_tool(agent_manager=am, registry=registry, base_dir=tmp_path, context=_ctx(tmp_path))
    long_task = "x" * 4001
    result = tool.func(task=long_task, role="researcher", allowed_tools=["web_search"])
    data = json.loads(result)
    assert "error" in data


def test_delegate_child_runtime_preserves_agent_identity_and_scope(tmp_path: Path):
    registry = DelegateRegistry(base_dir=tmp_path)
    runtime = _runtime_with_delegation(
        {
            "researcher": ["web_search", "fetch_url", "terminal"],
        }
    )
    runtime.root_dir = tmp_path / "workspaces" / "alpha"
    runtime.root_dir.mkdir(parents=True, exist_ok=True)

    parent_messages: list[dict[str, object]] = []

    class _Repository:
        async def append_message(self, **kwargs):
            parent_messages.append(kwargs)

    captured_request: dict[str, object] = {}

    class _GraphRuntime:
        async def invoke(self, request):
            captured_request["request"] = request
            return SimpleNamespace(
                messages=[
                    SimpleNamespace(type="assistant", content="Delegated answer"),
                    SimpleNamespace(type="tool", name="fetch_url"),
                ],
                token_usage={"prompt_tokens": 12, "completion_tokens": 3},
            )

    am = MagicMock()
    am.get_runtime.return_value = runtime
    am.get_session_repository.return_value = _Repository()
    am.graph_registry.resolve.return_value = _GraphRuntime()

    tool = build_delegate_tool(
        agent_manager=am,
        registry=registry,
        base_dir=tmp_path,
        context=_ctx(tmp_path, agent_id="alpha"),
    )

    async def _exercise() -> tuple[dict[str, object], object]:
        payload = json.loads(
            tool.func(
                task="Investigate APIs",
                role="researcher",
                allowed_tools=["fetch_url"],
                blocked_tools=["terminal"],
            )
        )
        state = registry.get_status(payload["delegate_id"])
        assert state is not None and state.task_ref is not None
        await state.task_ref
        return payload, state

    payload, state = asyncio.run(_exercise())

    assert payload["status"] == "running"
    assert state.status == "completed"
    am.get_runtime.assert_any_call("alpha")
    request = captured_request["request"]
    assert request.agent_id == "alpha"
    assert request.session_id == state.sub_session_id
    assert "Original delegated task:" in request.message
    assert "Investigate APIs" in request.message
    assert request.explicit_enabled_tools == ["fetch_url"]
    assert request.explicit_blocked_tools == ["terminal"]
    runtime.session_manager.create_session.assert_awaited_once()
    _, kwargs = runtime.session_manager.create_session.await_args
    assert kwargs["hidden"] is True
    assert kwargs["internal"] is True
    assert len(parent_messages) >= 2
    assert parent_messages[0]["delegate"]["status"] == "started"
    assert parent_messages[-1]["delegate"]["status"] == "completed"


def test_delegate_ainvoke_schedules_background_subagent(tmp_path: Path):
    registry = DelegateRegistry(base_dir=tmp_path)
    runtime = _runtime_with_delegation(
        {
            "researcher": ["web_search", "fetch_url", "terminal"],
        }
    )
    runtime.root_dir = tmp_path / "workspaces" / "alpha"
    runtime.root_dir.mkdir(parents=True, exist_ok=True)

    class _Repository:
        async def append_message(self, **kwargs):
            return None

    class _GraphRuntime:
        async def invoke(self, request):
            return SimpleNamespace(
                messages=[SimpleNamespace(type="assistant", content="Delegated answer")],
                token_usage={"prompt_tokens": 5, "completion_tokens": 2},
            )

    am = MagicMock()
    am.get_runtime.return_value = runtime
    am.get_session_repository.return_value = _Repository()
    am.graph_registry.resolve.return_value = _GraphRuntime()

    tool = build_delegate_tool(
        agent_manager=am,
        registry=registry,
        base_dir=tmp_path,
        context=_ctx(tmp_path, agent_id="alpha"),
    )

    async def _exercise() -> tuple[dict[str, object], object]:
        payload = json.loads(
            await tool.ainvoke(
                {
                    "task": "Investigate APIs",
                    "role": "researcher",
                    "allowed_tools": ["fetch_url"],
                    "blocked_tools": ["terminal"],
                }
            )
        )
        state = registry.get_status(payload["delegate_id"])
        assert state is not None
        assert state.task_ref is not None
        await state.task_ref
        return payload, state

    payload, state = asyncio.run(_exercise())

    assert payload["status"] in {"running", "completed"}
    assert state.status == "completed"
    runtime.session_manager.create_session.assert_awaited_once()


def test_delegate_ainvoke_returns_completed_payload_for_fast_delegate(tmp_path: Path):
    registry = DelegateRegistry(base_dir=tmp_path)
    runtime = _runtime_with_delegation(
        {
            "researcher": ["web_search", "fetch_url", "terminal"],
        }
    )
    runtime.root_dir = tmp_path / "workspaces" / "alpha"
    runtime.root_dir.mkdir(parents=True, exist_ok=True)

    class _Repository:
        async def append_message(self, **kwargs):
            return None

    class _GraphRuntime:
        async def invoke(self, request):
            return SimpleNamespace(
                messages=[
                    SimpleNamespace(type="assistant", content="Delegated answer"),
                    SimpleNamespace(type="tool", name="fetch_url"),
                ],
                token_usage={"prompt_tokens": 5, "completion_tokens": 2},
            )

    am = MagicMock()
    am.get_runtime.return_value = runtime
    am.get_session_repository.return_value = _Repository()
    am.graph_registry.resolve.return_value = _GraphRuntime()

    tool = build_delegate_tool(
        agent_manager=am,
        registry=registry,
        base_dir=tmp_path,
        context=_ctx(tmp_path, agent_id="alpha"),
    )

    payload = json.loads(
        asyncio.run(
            tool.ainvoke(
                {
                    "task": "Investigate APIs",
                    "role": "researcher",
                    "allowed_tools": ["fetch_url"],
                }
            )
        )
    )

    assert payload["status"] == "completed"
    assert payload["result_summary"] == "Delegated answer"
    assert payload["tools_used"] == ["fetch_url"]
