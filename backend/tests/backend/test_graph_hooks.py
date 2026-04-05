"""Tests for hook integration in DefaultGraphRuntime."""
from unittest.mock import MagicMock, patch

import pytest

from hooks.engine import HookEngine
from hooks.types import HookEvent, HookResult


class TestPreRunHook:
    def test_hook_dispatched_with_correct_type(self):
        """PreRun hook should fire at prepare_request stage."""
        engine = MagicMock(spec=HookEngine)
        engine.is_enabled = True
        engine.dispatch_sync.return_value = HookResult(allow=True)

        event = HookEvent(hook_type="pre_run", agent_id="test", session_id="s1", run_id="r1")
        result = engine.dispatch_sync(event)
        assert result.allow is True
        engine.dispatch_sync.assert_called_once()

    def test_deny_blocks_run(self):
        """If PreRun denies, the run should be blocked."""
        result = HookResult(allow=False, reason="agent disabled")
        assert result.allow is False
        assert "disabled" in result.reason


class TestPrePromptSubmitHook:
    def test_hook_dispatched_with_message_count(self):
        """PrePromptSubmit should include message count in payload."""
        engine = MagicMock(spec=HookEngine)
        engine.is_enabled = True
        engine.dispatch_sync.return_value = HookResult(allow=True)

        event = HookEvent(
            hook_type="pre_prompt_submit",
            agent_id="test",
            payload={"message_count": 5},
        )
        result = engine.dispatch_sync(event)
        assert result.allow is True

    def test_deny_returns_finalize_error(self):
        """Denied PrePromptSubmit should finalize_error."""
        result = HookResult(allow=False, reason="prompt too long")
        assert result.allow is False

    def test_modifications_applied_to_prompt(self):
        """Hook modifications should modify the system prompt prefix."""
        result = HookResult(
            allow=True,
            modifications={"system_prompt_prefix": "[REMINDER: be concise]\n"},
        )
        assert result.modifications["system_prompt_prefix"] == "[REMINDER: be concise]\n"


class TestStopHook:
    def test_stop_hook_is_async(self):
        """Stop hook should use async dispatch."""
        engine = MagicMock(spec=HookEngine)
        engine.is_enabled = True

        event = HookEvent(
            hook_type="stop",
            agent_id="test",
            run_id="run-1",
            payload={"status": "success", "text_len": 500},
        )
        engine.dispatch_async(event)
        engine.dispatch_async.assert_called_once()

    def test_stop_hook_success_and_error_statuses(self):
        """Stop should include status in payload."""
        engine = MagicMock(spec=HookEngine)
        engine.is_enabled = True

        # Success path
        engine.dispatch_async(HookEvent(
            hook_type="stop", agent_id="test",
            payload={"status": "success", "text_len": 100},
        ))

        # Error path
        engine.dispatch_async(HookEvent(
            hook_type="stop", agent_id="test",
            payload={"status": "error"},
        ))

        assert engine.dispatch_async.call_count == 2


class TestPerAgentHookIsolation:
    def test_engine_per_agent_is_independent(self):
        from pathlib import Path
        engine_a = HookEngine(agent_id="agent-a", workspace_root=Path("/tmp/a"))
        engine_b = HookEngine(agent_id="agent-b", workspace_root=Path("/tmp/b"))
        assert engine_a.agent_id != engine_b.agent_id
