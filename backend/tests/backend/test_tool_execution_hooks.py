"""Tests for PreToolUse/PostToolUse hook integration in tool_execution."""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from config import load_runtime_config
from graph.tool_execution import ToolExecutionService
from hooks.engine import HookEngine, _clear_handler_cache
from storage.run_store import AuditStore


@pytest.fixture(autouse=True)
def clear_cache():
    _clear_handler_cache()
    yield
    _clear_handler_cache()


class TestPreToolUseHookIntegration:
    @pytest.mark.asyncio
    async def test_hook_denies_tool_execution(self, tmp_path: Path):
        """When PreToolUse hook denies, tool should not be invoked."""
        handler_dir = tmp_path / "hooks"
        handler_dir.mkdir()
        (handler_dir / "deny.py").write_text(
            "from hooks.types import HookEvent, HookResult\n"
            "def handle(e): return HookResult(allow=False, reason='tool not allowed')"
        )
        (tmp_path / "hooks.json").write_text(
            '{"hooks":[{"id":"d","type":"pre_tool_use","handler":"hooks/deny.py","mode":"sync"}]}'
        )
        engine = HookEngine(agent_id="test", workspace_root=tmp_path)
        engine.load_config()

        mock_tool = AsyncMock()
        mock_tool.name = "terminal"
        mock_tool.ainvoke = AsyncMock(return_value='{"ok": true, "meta": {"duration_ms": 0}}')

        service = ToolExecutionService(
            tools=[mock_tool],
            tools_by_name={"terminal": mock_tool},
            hook_engine=engine,
        )

        tool_calls = [{"name": "terminal", "id": "call-1", "args": {"command": "rm -rf /"}}]
        envelopes, tool_msgs = await service.execute_pending(tool_calls)

        assert len(envelopes) == 1
        assert envelopes[0].ok is False
        assert envelopes[0].error_code == "E_POLICY_DENIED"
        assert "Hook denied" in envelopes[0].error_message
        mock_tool.ainvoke.assert_not_called()

    @pytest.mark.asyncio
    async def test_hook_allows_tool_execution(self, tmp_path: Path):
        """When PreToolUse hook allows, tool should be invoked normally."""
        handler_dir = tmp_path / "hooks"
        handler_dir.mkdir()
        (handler_dir / "allow.py").write_text(
            "from hooks.types import HookEvent, HookResult\n"
            "def handle(e): return HookResult(allow=True)"
        )
        (tmp_path / "hooks.json").write_text(
            '{"hooks":[{"id":"a","type":"pre_tool_use","handler":"hooks/allow.py","mode":"sync"}]}'
        )
        engine = HookEngine(agent_id="test", workspace_root=tmp_path)
        engine.load_config()

        mock_tool = AsyncMock()
        mock_tool.name = "terminal"
        mock_tool.ainvoke = AsyncMock(return_value='{"ok": true, "meta": {"duration_ms": 100}}')

        service = ToolExecutionService(
            tools=[mock_tool],
            tools_by_name={"terminal": mock_tool},
            hook_engine=engine,
        )

        tool_calls = [{"name": "terminal", "id": "call-1", "args": {"command": "ls"}}]
        envelopes, tool_msgs = await service.execute_pending(tool_calls)

        assert len(envelopes) == 1
        assert envelopes[0].ok is True
        mock_tool.ainvoke.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_hook_engine_means_normal_execution(self, tmp_path: Path):
        """If no hook_engine is set, tool executes normally."""
        mock_tool = AsyncMock()
        mock_tool.name = "terminal"
        mock_tool.ainvoke = AsyncMock(return_value='{"ok": true, "meta": {"duration_ms": 50}}')

        service = ToolExecutionService(
            tools=[mock_tool],
            tools_by_name={"terminal": mock_tool},
            hook_engine=None,
        )

        tool_calls = [{"name": "terminal", "id": "call-1", "args": {"command": "ls"}}]
        envelopes, tool_msgs = await service.execute_pending(tool_calls)

        assert len(envelopes) == 1
        assert envelopes[0].ok is True
        mock_tool.ainvoke.assert_called_once()

    @pytest.mark.asyncio
    async def test_tool_still_works_when_hook_raises_exception(self, tmp_path: Path):
        """Hook exception should deny tool execution (fail-closed)."""
        handler_dir = tmp_path / "hooks"
        handler_dir.mkdir()
        (handler_dir / "crash.py").write_text(
            "from hooks.types import HookEvent, HookResult\n"
            "def handle(e): raise RuntimeError('crash')"
        )
        (tmp_path / "hooks.json").write_text(
            '{"hooks":[{"id":"c","type":"pre_tool_use","handler":"hooks/crash.py","mode":"sync"}]}'
        )
        engine = HookEngine(agent_id="test", workspace_root=tmp_path)
        engine.load_config()

        mock_tool = AsyncMock()
        mock_tool.name = "terminal"
        mock_tool.ainvoke = AsyncMock()

        service = ToolExecutionService(
            tools=[mock_tool],
            tools_by_name={"terminal": mock_tool},
            hook_engine=engine,
        )

        tool_calls = [{"name": "terminal", "id": "call-1", "args": {}}]
        envelopes, tool_msgs = await service.execute_pending(tool_calls)

        assert len(envelopes) == 1
        assert envelopes[0].ok is False
        mock_tool.ainvoke.assert_not_called()

    @pytest.mark.asyncio
    async def test_tool_hooks_capture_context_and_audit_rows(self, tmp_path: Path):
        handler_dir = tmp_path / "hooks"
        handler_dir.mkdir()
        event_file = tmp_path / "hook_event.json"
        (handler_dir / "capture.py").write_text(
            "import json\n"
            f"EVENT_PATH = {str(event_file)!r}\n"
            "from hooks.types import HookResult\n"
            "def handle(event):\n"
            "    with open(EVENT_PATH, 'w', encoding='utf-8') as fh:\n"
            "        json.dump({\n"
            "            'agent_id': event.agent_id,\n"
            "            'session_id': event.session_id,\n"
            "            'run_id': event.run_id,\n"
            "            'timestamp': event.timestamp,\n"
            "            'tool_name': event.payload.get('tool_name'),\n"
            "        }, fh)\n"
            "    return HookResult(allow=True)\n"
        )
        (tmp_path / "hooks.json").write_text(
            '{"hooks":[{"id":"c","type":"pre_tool_use","handler":"hooks/capture.py","mode":"sync"},'
            '{"id":"p","type":"post_tool_use","handler":"hooks/capture.py","mode":"async"}]}'
        )
        (tmp_path / "config.json").write_text('{"rag_mode": false}\n', encoding="utf-8")
        engine = HookEngine(agent_id="agent-a", workspace_root=tmp_path)
        engine.load_config()

        runtime = load_runtime_config(tmp_path / "config.json")
        service = ToolExecutionService.build(
            config_base_dir=tmp_path,
            runtime_root=tmp_path,
            runtime=runtime,
            trigger_type="chat",
            agent_id="agent-a",
            run_id="run-7",
            session_id="session-9",
            runtime_audit_store=AuditStore(tmp_path),
            hook_engine=engine,
            explicit_enabled_tools=None,
            explicit_blocked_tools=None,
        )

        tool_calls = [{"name": "read_files", "id": "call-1", "args": {"path": "hooks.json"}}]
        envelopes, _ = await service.execute_pending(tool_calls)

        assert len(envelopes) == 1
        event_payload = json.loads(event_file.read_text(encoding="utf-8"))
        assert event_payload["agent_id"] == "agent-a"
        assert event_payload["session_id"] == "session-9"
        assert event_payload["run_id"] == "run-7"
        assert event_payload["tool_name"] == "read_files"
        assert event_payload["timestamp"]

        rows = [
            json.loads(line)
            for line in (tmp_path / "storage" / "audit" / "steps.jsonl").read_text(
                encoding="utf-8"
            ).splitlines()
            if line.strip()
        ]
        assert [row["event"] for row in rows[-2:]] == [
            "hook_pre_tool_use",
            "hook_post_tool_use",
        ]
