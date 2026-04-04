import json
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

from tools.base import ToolContext
from tools.delegate_registry import DelegateRegistry
from tools.delegate_tool import build_delegate_tool


def _ctx(root: Path, session: str = "parent_session") -> ToolContext:
    return ToolContext(workspace_root=root, trigger_type="chat", session_id=session, run_id="run_1")


def test_delegate_tool_name(tmp_path: Path):
    registry = DelegateRegistry(base_dir=tmp_path)
    am = MagicMock()
    tool = build_delegate_tool(agent_manager=am, registry=registry, base_dir=tmp_path, context=_ctx(tmp_path))
    assert tool.name == "delegate"


def test_rejects_empty_task(tmp_path: Path):
    registry = DelegateRegistry(base_dir=tmp_path)
    am = MagicMock()
    tool = build_delegate_tool(agent_manager=am, registry=registry, base_dir=tmp_path, context=_ctx(tmp_path))
    result = tool.func(task="", role="researcher", allowed_tools=["web_search"])
    data = json.loads(result)
    assert "error" in data


def test_rejects_empty_tools(tmp_path: Path):
    registry = DelegateRegistry(base_dir=tmp_path)
    am = MagicMock()
    tool = build_delegate_tool(agent_manager=am, registry=registry, base_dir=tmp_path, context=_ctx(tmp_path))
    result = tool.func(task="Do something", role="researcher", allowed_tools=[])
    data = json.loads(result)
    assert "error" in data


def test_rejects_delegate_in_allowed(tmp_path: Path):
    registry = DelegateRegistry(base_dir=tmp_path)
    am = MagicMock()
    tool = build_delegate_tool(agent_manager=am, registry=registry, base_dir=tmp_path, context=_ctx(tmp_path))
    result = tool.func(task="Task", role="researcher", allowed_tools=["delegate"])
    data = json.loads(result)
    assert "error" in data


def test_launches_successfully(tmp_path: Path):
    registry = DelegateRegistry(base_dir=tmp_path)
    am = MagicMock()
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
    tool = build_delegate_tool(agent_manager=am, registry=registry, base_dir=tmp_path, context=_ctx(tmp_path))
    long_task = "x" * 4001
    result = tool.func(task=long_task, role="researcher", allowed_tools=["web_search"])
    data = json.loads(result)
    assert "error" in data
