"""Edge case tests for hooks and compaction subsystems."""
import asyncio
import json
import time
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from hooks.engine import HookEngine, _clear_handler_cache
from hooks.types import HookEvent, HookResult, HookConfig, HookType
from graph.compaction import CompactionPipeline, CompactionSummary, count_tokens


# ── Helpers ─────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clear_cache():
    _clear_handler_cache()
    yield
    _clear_handler_cache()


@pytest.fixture
def engine(tmp_path: Path) -> HookEngine:
    return HookEngine(agent_id="test-agent", workspace_root=tmp_path)


def _setup_handler(tmp: Path, name: str, code: str) -> None:
    handler_dir = tmp / "hooks"
    handler_dir.mkdir(exist_ok=True)
    (handler_dir / name).write_text(code)


# ═══════════════════════════════════════════════════════════════
# Hook Engine Edge Cases
# ═══════════════════════════════════════════════════════════════

class TestHookEngineEdgeCases:

    def test_malformed_hooks_json(self, engine, tmp_path):
        """Malformed JSON should not crash engine, should clear hooks."""
        (tmp_path / "hooks.json").write_text("{invalid json!!!")
        engine.load_config()
        assert len(engine.list_hooks()) == 0
        assert engine.is_enabled is True

    def test_empty_hooks_json(self, engine, tmp_path):
        (tmp_path / "hooks.json").write_text("{}")
        engine.load_config()
        assert len(engine.list_hooks()) == 0

    def test_hooks_json_with_empty_list(self, engine, tmp_path):
        (tmp_path / "hooks.json").write_text('{"hooks": []}')
        engine.load_config()
        assert len(engine.list_hooks()) == 0

    def test_partial_hook_config_missing_type(self, engine, tmp_path):
        (tmp_path / "hooks.json").write_text('{"hooks": [{"id": "x", "handler": "hooks/x.py"}]}')
        engine.load_config()
        assert len(engine.list_hooks()) == 0

    def test_invalid_hook_type_string(self, engine, tmp_path):
        _setup_handler(tmp_path, "x.py", "def handle(e): pass")
        (tmp_path / "hooks.json").write_text(
            '{"hooks": [{"id": "x", "type": "not_a_hook_type", "handler": "hooks/x.py"}]}'
        )
        engine.load_config()
        assert len(engine.list_hooks()) == 0

    def test_handler_without_handle_function_raises(self, engine, tmp_path):
        """Handler file without handle() should raise ImportError when loaded."""
        _setup_handler(tmp_path, "nohandle.py", "def other(): pass")
        (tmp_path / "hooks.json").write_text(
            '{"hooks": [{"id": "nh", "type": "pre_tool_use", "handler": "hooks/nohandle.py", "mode": "sync"}]}'
        )
        engine.load_config()
        # load_config only checks file exists, so hook is registered
        assert len(engine.list_hooks()) == 1
        # But _load_handler should raise ImportError at dispatch time
        _clear_handler_cache()
        with pytest.raises(ImportError, match="handle"):
            engine._load_handler("hooks/nohandle.py")

    def test_multiple_hooks_first_deny_wins(self, engine, tmp_path):
        """When multiple hooks of same type exist, first deny blocks all."""
        _setup_handler(tmp_path, "deny.py",
            "from hooks.types import HookEvent, HookResult\ndef handle(e): return HookResult(allow=False, reason='denied')")
        _setup_handler(tmp_path, "allow.py",
            "from hooks.types import HookEvent, HookResult\ndef handle(e): raise RuntimeError('should not reach')")
        (tmp_path / "hooks.json").write_text(json.dumps({
            "hooks": [
                {"id": "d", "type": "pre_tool_use", "handler": "hooks/deny.py", "mode": "sync"},
                {"id": "a", "type": "pre_tool_use", "handler": "hooks/allow.py", "mode": "sync"},
            ]
        }))
        engine.load_config()
        result = engine.dispatch_sync(HookEvent(hook_type="pre_tool_use", agent_id="test"))
        assert result.allow is False
        assert "denied" in result.reason

    def test_modifications_chained_between_hooks(self, tmp_path):
        """Modifications from first hook should be passed to second via event.payload."""
        _setup_handler(tmp_path, "m1.py",
            "from hooks.types import HookEvent, HookResult\ndef handle(e):\n    e.payload['step1'] = 'done'\n    return HookResult(allow=True, modifications={'prefix': '[M1]'})")
        _setup_handler(tmp_path, "m2.py",
            "from hooks.types import HookEvent, HookResult\ndef handle(e):\n    assert e.payload.get('step1') == 'done'\n    return HookResult(allow=True, reason='ok')")
        (tmp_path / "hooks.json").write_text(json.dumps({
            "hooks": [
                {"id": "m1", "type": "pre_prompt_submit", "handler": "hooks/m1.py", "mode": "sync"},
                {"id": "m2", "type": "pre_prompt_submit", "handler": "hooks/m2.py", "mode": "sync"},
            ]
        }))
        engine = HookEngine(agent_id="t", workspace_root=tmp_path)
        engine.load_config()
        result = engine.dispatch_sync(HookEvent(hook_type="pre_prompt_submit", agent_id="t"))
        assert result.allow is True
        assert result.modifications.get("prefix") == "[M1]"

    def test_is_enabled_flag(self, engine, tmp_path):
        """is_enabled flag can be toggled (caller responsibility to check)."""
        _setup_handler(tmp_path, "deny.py",
            "from hooks.types import HookEvent, HookResult\ndef handle(e): return HookResult(allow=False)")
        (tmp_path / "hooks.json").write_text(json.dumps({
            "hooks": [
                {"id": "d", "type": "pre_tool_use", "handler": "hooks/deny.py", "mode": "sync"},
            ]
        }))
        engine.load_config()
        # dispatch_sync doesn't check is_enabled — that's the caller's job
        result = engine.dispatch_sync(HookEvent(hook_type="pre_tool_use", agent_id="test"))
        assert result.allow is False

    def test_cache_invalidation_on_file_change(self, engine, tmp_path):
        """Changing handler file + clearing cache should cause reimport."""
        _setup_handler(tmp_path, "v1.py",
            "from hooks.types import HookEvent, HookResult\nVERSION = 1\ndef handle(e): return HookResult(allow=True, reason=f'v{VERSION}')")
        (tmp_path / "hooks.json").write_text(json.dumps({
            "hooks": [{"id": "v", "type": "pre_tool_use", "handler": "hooks/v1.py", "mode": "sync"}]
        }))
        engine.load_config()
        result = engine.dispatch_sync(HookEvent(hook_type="pre_tool_use", agent_id="test"))
        assert "v1" in result.reason

        # Change handler file content
        time.sleep(0.1)  # ensure mtime changes
        (tmp_path / "hooks" / "v1.py").write_text(
            "from hooks.types import HookEvent, HookResult\nVERSION = 2\ndef handle(e): return HookResult(allow=True, reason=f'v{VERSION}')"
        )
        _clear_handler_cache()
        engine.load_config()
        result = engine.dispatch_sync(HookEvent(hook_type="pre_tool_use", agent_id="test"))
        assert "v2" in result.reason

    def test_very_short_timeout(self, engine, tmp_path):
        """A handler that exceeds timeout_ms should timeout and default allow."""
        _setup_handler(tmp_path, "slow.py",
            "import time\nfrom hooks.types import HookEvent, HookResult\ndef handle(e):\n    time.sleep(5)\n    return HookResult(allow=False)")
        (tmp_path / "hooks.json").write_text(json.dumps({
            "hooks": [{"id": "s", "type": "pre_tool_use", "handler": "hooks/slow.py", "mode": "sync", "timeout_ms": 50}]
        }))
        engine.load_config()
        result = engine.dispatch_sync(HookEvent(hook_type="pre_tool_use", agent_id="test"))
        assert result.allow is True
        assert "timed out" in result.reason.lower()

    def test_remove_nonexistent_hook(self, engine):
        assert engine.remove_hook("does-not-exist") is False

    def test_add_and_remove_persistence(self, engine, tmp_path):
        """add_hook and remove_hook should persist to hooks.json."""
        _setup_handler(tmp_path, "test.py", "def handle(e): pass")
        engine.add_hook(HookConfig(
            id="test", type=HookType.PRE_TOOL_USE, handler="hooks/test.py", mode="sync"
        ))
        assert len(engine.list_hooks()) == 1
        # Reload
        engine2 = HookEngine(agent_id="t", workspace_root=tmp_path)
        engine2.load_config()
        assert len(engine2.list_hooks()) == 1
        engine2.remove_hook("test")
        assert len(engine2.list_hooks()) == 0
        # Reload again
        engine3 = HookEngine(agent_id="t", workspace_root=tmp_path)
        engine3.load_config()
        assert len(engine3.list_hooks()) == 0


# ═══════════════════════════════════════════════════════════════
# Compaction Edge Cases
# ═══════════════════════════════════════════════════════════════

class TestCompactionEdgeCases:

    def test_empty_messages(self):
        pipeline = CompactionPipeline(model_name="gpt-4o")
        needs, budget = pipeline.needs_compaction([], token_count=0)
        assert needs is False

    def test_only_system_messages(self):
        pipeline = CompactionPipeline(model_name="gpt-4o")
        messages = [SystemMessage(content="You are a bot")]
        needs, budget = pipeline.needs_compaction(messages, token_count=1000)
        assert needs is False

    def test_exact_boundary_does_not_trigger(self):
        """token_count == threshold should NOT trigger compaction (strict >)."""
        pipeline = CompactionPipeline(model_name="gpt-4o", budget_factor=0.85)
        threshold = int(pipeline.compute_budget() * 0.85)
        needs, _ = pipeline.needs_compaction([], token_count=threshold)
        assert needs is False
        needs, _ = pipeline.needs_compaction([], token_count=threshold + 1)
        assert needs is True

    def test_drop_with_only_system_messages(self):
        """Drop with only system messages: summary still added, no dropped."""
        pipeline = CompactionPipeline(model_name="gpt-4o")
        messages = [SystemMessage(content="sys1"), SystemMessage(content="sys2")]
        remaining, dropped = pipeline.drop(messages, "summary", keep_last=4)
        assert len(dropped) == 0
        assert len(remaining) == 3  # 2 system + 1 summary
        assert all(isinstance(m, SystemMessage) for m in remaining[:2])

    def test_drop_keep_last_larger_than_messages(self):
        """Edge: keep_last > total non-system → keep all."""
        pipeline = CompactionPipeline(model_name="gpt-4o")
        messages = [SystemMessage(content="sys"), HumanMessage(content="only one")]
        remaining, dropped = pipeline.drop(messages, "summary", keep_last=10)
        assert len(dropped) == 0
        assert len(remaining) == 3  # 1 system + 1 summary + 1 human

    def test_drop_zero_keep(self):
        """Edge: keep_last=0 drops ALL non-system messages, inserts summary."""
        pipeline = CompactionPipeline(model_name="gpt-4o")
        messages = [SystemMessage(content="sys"), HumanMessage(content="a"), AIMessage(content="b")]
        remaining, dropped = pipeline.drop(messages, "summary", keep_last=0)
        assert len(dropped) == 2  # human + ai
        assert len(remaining) == 2  # system + summary
        assert any("summary" in str(m.content).lower() for m in remaining)

    def test_checkpoint_no_directory(self):
        """checkpoint_dir=None should not crash, just skip checkpoint."""
        pipeline = CompactionPipeline(model_name="gpt-4o", checkpoint_dir=None)
        messages = [HumanMessage(content="test")]

        async def run():
            cp_id = await pipeline.create_checkpoint(messages, run_id="r", step=1)
            assert cp_id  # ID is always generated
            assert pipeline.checkpoint_dir is None

        asyncio.get_event_loop().run_until_complete(run())

    def test_checkpoint_load_from_empty_directory(self, tmp_path):
        """Loading from empty checkpoint dir should raise FileNotFoundError."""
        pipeline = CompactionPipeline(model_name="gpt-4o", checkpoint_dir=tmp_path)

        async def run():
            with pytest.raises(FileNotFoundError):
                await pipeline.load_checkpoint("nonexistent")

        asyncio.get_event_loop().run_until_complete(run())

    def test_checkpoint_list_from_empty_directory(self, tmp_path):
        pipeline = CompactionPipeline(model_name="gpt-4o", checkpoint_dir=tmp_path)

        async def run():
            cps = await pipeline.list_checkpoints()
            assert cps == []

        asyncio.get_event_loop().run_until_complete(run())

    def test_checkpoint_id_format(self, tmp_path):
        """Checkpoint ID should follow expected pattern."""
        pipeline = CompactionPipeline(model_name="gpt-4o", checkpoint_dir=tmp_path)
        msgs = [HumanMessage(content="test")]

        async def run():
            cp_id = await pipeline.create_checkpoint(msgs, run_id="my-run-id-12345", step=42)
            assert cp_id.startswith("ckpt_my-run-")
            assert "0042" in cp_id

        asyncio.get_event_loop().run_until_complete(run())

    def test_llm_summarize_raises_by_default(self):
        """llm_summarize should raise NotImplementedError when no LCEL binding."""
        async def run():
            with pytest.raises(NotImplementedError, match="LCEL"):
                await CompactionPipeline(model_name="gpt-4o").llm_summarize(
                    [HumanMessage(content="test")]
                )

        asyncio.get_event_loop().run_until_complete(run())

    def test_distill_appends_multiple_times(self, tmp_path):
        """Multiple distill calls should append, not overwrite."""
        memory_file = tmp_path / "MEMORY.md"
        memory_file.write_text("# MEMORY.md\n")
        pipeline = CompactionPipeline(model_name="gpt-4o")
        s1 = CompactionSummary(summary="First", key_decisions=["D1"])
        s2 = CompactionSummary(summary="Second", key_decisions=["D2"])

        async def run():
            await pipeline.distill(s1, memory_file=memory_file)
            await pipeline.distill(s2, memory_file=memory_file)

        asyncio.get_event_loop().run_until_complete(run())
        content = memory_file.read_text()
        assert "First" in content
        assert "Second" in content
        assert content.count("Compaction") == 2

    def test_distill_with_special_characters(self, tmp_path):
        """Summary with special chars should not corrupt MEMORY.md."""
        memory_file = tmp_path / "MEMORY.md"
        memory_file.write_text("# MEMORY.md\n")
        pipeline = CompactionPipeline(model_name="gpt-4o")
        summary = CompactionSummary(
            summary="Use `sys.exit()` not `exit()` 🐛 $100",
            key_decisions=["Use `rm -rf` (with caution!)"],
        )

        async def run():
            await pipeline.distill(summary, memory_file=memory_file)

        asyncio.get_event_loop().run_until_complete(run())
        content = memory_file.read_text()
        assert "🐛" in content
        assert "rm -rf" in content

    def test_count_tokens_long_text(self):
        """Large text should not crash or return wrong values."""
        text = "hello " * 100_000
        result = count_tokens(text)
        assert result > 0
        assert result < 200_000  # sanity check

    def test_compact_round_with_very_long_messages(self, tmp_path):
        """Verify compaction triggers and reduces with real token counts."""
        pipeline = CompactionPipeline(model_name="gpt-4o", checkpoint_dir=tmp_path, budget_factor=0.15)
        large_content = "A" * 100_000  # ~12.5k tokens per message
        messages = [
            SystemMessage(content="sys"),
            HumanMessage(content=large_content),
            HumanMessage(content=large_content),
            HumanMessage(content=large_content),
            HumanMessage(content=large_content),
        ]

        total = pipeline.count_messages_tokens(messages)
        threshold = int(pipeline.compute_budget() * pipeline.budget_factor)
        assert total > threshold, f"Need >{threshold}, got {total}"

        async def fake_summarize(msgs):
            return CompactionSummary(summary="summarized large content", key_decisions=["Big msgs"])

        async def run():
            result = await pipeline.compact_round(
                messages, run_id="large", step=1, summarize_fn=fake_summarize
            )
            assert result.was_compacted is True
            assert result.checkpoint_id is not None
            # 1 system + 1 summary + 4 human = 6
            assert len(result.messages) == 6
            assert any("summarized large content" in str(m.content) for m in result.messages)

        asyncio.get_event_loop().run_until_complete(run())

    def test_needs_compaction_with_custom_budget_factor(self):
        """budget_factor=1.0 means compact at 100% of 80% budget."""
        pipeline = CompactionPipeline(model_name="gpt-4o", budget_factor=1.0)
        budget = pipeline.compute_budget()  # 102400
        needs, _ = pipeline.needs_compaction([], token_count=budget)
        assert needs is False  # exactly at threshold
        needs, _ = pipeline.needs_compaction([], token_count=budget + 1)
        assert needs is True

    def test_drop_with_single_message(self):
        """Edge: 1 non-system, keep_last=1."""
        pipeline = CompactionPipeline(model_name="gpt-4o")
        messages = [SystemMessage(content="sys"), HumanMessage(content="only")]
        remaining, dropped = pipeline.drop(messages, "summary", keep_last=1)
        assert len(dropped) == 0
        assert len(remaining) == 3  # sys + summary + only

    def test_compact_round_no_compaction_needed(self):
        """Compact round on small messages should return unchanged."""
        async def run():
            pipeline = CompactionPipeline(model_name="gpt-4o")
            messages = [HumanMessage(content="hello")]
            result = await pipeline.compact_round(messages, run_id="r1", step=1)
            assert result.was_compacted is False
            assert result.summary is None
            assert result.messages is messages

        asyncio.get_event_loop().run_until_complete(run())
