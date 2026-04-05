"""Tests for PreToolUse/PostToolUse hook integration in tool_execution."""
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from graph.tool_execution import ToolExecutionService
from hooks.engine import HookEngine, _clear_handler_cache


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
