# backend/tests/backend/test_hooks_types.py
import pytest
from hooks.types import HookEvent, HookResult, HookConfig, HookType


class TestHookType:
    def test_all_hook_types_exist(self):
        expected = [
            "pre_prompt_submit",
            "pre_tool_use",
            "post_tool_use",
            "pre_compact",
            "stop",
            "pre_run",
        ]
        for name in expected:
            assert HookType(name) is not None


class TestHookEvent:
    def test_create_hook_event(self):
        event = HookEvent(
            hook_type="pre_tool_use",
            agent_id="test-agent",
            session_id="sess-1",
            run_id="run-1",
            payload={"tool_name": "terminal", "input": {"command": "ls"}},
            timestamp="2026-04-05T00:00:00Z",
        )
        assert event.hook_type == "pre_tool_use"
        assert event.payload["tool_name"] == "terminal"


class TestHookResult:
    def test_allow_result(self):
        result = HookResult(allow=True, reason="All good")
        assert result.allow is True

    def test_deny_result(self):
        result = HookResult(allow=False, reason="Too dangerous")
        assert result.allow is False
        assert result.reason == "Too dangerous"

    def test_modifications_field(self):
        result = HookResult(
            allow=True,
            modifications={"system_prompt": "modified prompt"},
        )
        assert result.modifications["system_prompt"] == "modified prompt"


class TestHookConfig:
    def test_load_from_dict(self):
        config = HookConfig.from_dict({
            "id": "test-hook",
            "type": "pre_tool_use",
            "handler": "hooks/test.py",
            "mode": "sync",
            "timeout_ms": 5000,
        })
        assert config.id == "test-hook"
        assert config.type == HookType.PRE_TOOL_USE
        assert config.mode == "sync"
        assert config.timeout_ms == 5000

    def test_default_timeout(self):
        config = HookConfig.from_dict({
            "id": "test-2",
            "type": "post_tool_use",
            "handler": "hooks/audit.py",
            "mode": "async",
        })
        assert config.timeout_ms == 10000  # default
