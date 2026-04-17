import json
import time
from pathlib import Path

from tools.base import ToolContext
from tools.delegate_registry import DelegateRegistry
from tools.delegate_tool import build_delegate_status_tool


def test_status_running(tmp_path: Path):
    registry = DelegateRegistry(base_dir=tmp_path)
    reg = registry.register("alpha", "sess_1", "Research", "researcher", ["web_search"], [], 30)
    tool = build_delegate_status_tool(
        registry=registry,
        context=ToolContext(
            workspace_root=tmp_path,
            trigger_type="test",
            agent_id="alpha",
            session_id="sess_1",
        ),
    )
    result = json.loads(tool.func(delegate_id=reg["delegate_id"]))
    assert result["status"] == "running"
    assert result["delegate_id"] == reg["delegate_id"]


def test_status_not_found(tmp_path: Path):
    registry = DelegateRegistry(base_dir=tmp_path)
    tool = build_delegate_status_tool(
        registry=registry,
        context=ToolContext(
            workspace_root=tmp_path,
            trigger_type="test",
            agent_id="alpha",
            session_id="sess_1",
        ),
    )
    result = json.loads(tool.func(delegate_id="nonexistent"))
    assert "error" in result


def test_status_completed(tmp_path: Path):
    registry = DelegateRegistry(base_dir=tmp_path)
    reg = registry.register("alpha", "sess_1", "Task", "r", ["w"], [], 30)
    time.sleep(0.01)
    registry.mark_completed(reg["delegate_id"], {
        "summary": "Done",
        "steps": 5,
        "tools_used": ["web_search"],
        "token_usage": {"prompt_tokens": 100, "completion_tokens": 50},
    })
    tool = build_delegate_status_tool(
        registry=registry,
        context=ToolContext(
            workspace_root=tmp_path,
            trigger_type="test",
            agent_id="alpha",
            session_id="sess_1",
        ),
    )
    result = json.loads(tool.func(delegate_id=reg["delegate_id"]))
    assert result["status"] == "completed"
    assert result["result_summary"] == "Done"
    assert result["duration_ms"] > 0
