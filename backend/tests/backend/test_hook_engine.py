"""Tests for HookEngine — registry and dispatch."""
import asyncio
from pathlib import Path

import pytest

from hooks.engine import HookEngine, _clear_handler_cache
from hooks.types import HookEvent, HookResult, HookType


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear handler cache before each test to avoid stale modules."""
    _clear_handler_cache()
    yield
    _clear_handler_cache()


@pytest.fixture
def engine(tmp_path: Path) -> HookEngine:
    return HookEngine(agent_id="test-agent", workspace_root=tmp_path)


def _setup_handler(tmp: Path, name: str, code: str) -> None:
    """Helper: write a handler file to tmp/hooks/<name>.py"""
    handler_dir = tmp / "hooks"
    handler_dir.mkdir(exist_ok=True)
    (handler_dir / name).write_text(code)


class TestHookRegistry:
    def test_load_empty_has_no_hooks(self, engine: HookEngine, tmp_path: Path):
        assert engine.is_enabled is True
        assert len(engine.list_hooks()) == 0

    def test_load_with_valid_handler(self, engine: HookEngine, tmp_path: Path):
        _setup_handler(tmp_path, "audit.py", "def handle(e): pass")
        (tmp_path / "hooks.json").write_text('{"hooks":[{"id":"a","type":"post_tool_use","handler":"hooks/audit.py","mode":"async"}]}')
        engine.load_config()
        assert len(engine.list_hooks()) == 1

    def test_load_skips_missing_handler(self, engine: HookEngine, tmp_path: Path):
        (tmp_path / "hooks.json").write_text('{"hooks":[{"id":"a","type":"pre_tool_use","handler":"hooks/missing.py"}]}')
        engine.load_config()
        assert len(engine.list_hooks()) == 0

    def test_add_and_remove(self, engine: HookEngine, tmp_path: Path):
        _setup_handler(tmp_path, "test.py", "def handle(e): pass")
        from hooks.types import HookConfig
        engine.add_hook(HookConfig(id="t", type=HookType.PRE_TOOL_USE, handler="hooks/test.py", mode="sync"))
        assert len(engine.list_hooks()) == 1
        assert engine.remove_hook("t") is True
        assert engine.remove_hook("t") is False
        assert len(engine.list_hooks()) == 0


class TestDispatchSync:
    def test_no_hooks_returns_allow(self, engine: HookEngine):
        result = engine.dispatch_sync(HookEvent(hook_type="pre_tool_use", agent_id="test", payload={"tool_name": "ls"}))
        assert result.allow is True

    def test_handler_allows(self, engine: HookEngine, tmp_path: Path):
        _setup_handler(tmp_path, "allow.py",
            "from hooks.types import HookEvent, HookResult\ndef handle(e): return HookResult(allow=True)")
        (tmp_path / "hooks.json").write_text('{"hooks":[{"id":"a","type":"pre_tool_use","handler":"hooks/allow.py","mode":"sync"}]}')
        engine.load_config()
        result = engine.dispatch_sync(HookEvent(hook_type="pre_tool_use", agent_id="test"))
        assert result.allow is True

    def test_handler_denies(self, engine: HookEngine, tmp_path: Path):
        _setup_handler(tmp_path, "deny.py",
            "from hooks.types import HookEvent, HookResult\ndef handle(e): return HookResult(allow=False, reason='no')")
        (tmp_path / "hooks.json").write_text('{"hooks":[{"id":"d","type":"pre_tool_use","handler":"hooks/deny.py","mode":"sync"}]}')
        engine.load_config()
        result = engine.dispatch_sync(HookEvent(hook_type="pre_tool_use", agent_id="test"))
        assert result.allow is False
        assert result.reason == "no"

    def test_exception_fails_closed(self, engine: HookEngine, tmp_path: Path):
        _setup_handler(tmp_path, "crash.py",
            "from hooks.types import HookEvent, HookResult\ndef handle(e):\n    raise RuntimeError('boom')")
        (tmp_path / "hooks.json").write_text('{"hooks":[{"id":"c","type":"pre_tool_use","handler":"hooks/crash.py","mode":"sync"}]}')
        engine.load_config()
        result = engine.dispatch_sync(HookEvent(hook_type="pre_tool_use", agent_id="test"))
        assert result.allow is False
        assert "boom" in result.reason

    def test_timeout_defaults_allow(self, engine: HookEngine, tmp_path: Path):
        _setup_handler(tmp_path, "slow.py",
            "import time\nfrom hooks.types import HookEvent, HookResult\ndef handle(e):\n    time.sleep(10)\n    return HookResult(allow=False)")
        (tmp_path / "hooks.json").write_text('{"hooks":[{"id":"s","type":"pre_tool_use","handler":"hooks/slow.py","mode":"sync","timeout_ms":500}]}')
        engine.load_config()
        result = engine.dispatch_sync(HookEvent(hook_type="pre_tool_use", agent_id="test"))
        assert result.allow is True
        assert "timed out" in result.reason.lower()
