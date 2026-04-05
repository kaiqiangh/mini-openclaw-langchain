"""Tests for CompactionPipeline."""
import asyncio
import json
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from graph.compaction import (
    CompactionPipeline,
    CompactionSummary,
    CompactResult,
    count_tokens,
)


class TestCountTokens:
    def test_count_tokens_with_tiktoken_or_heuristic(self):
        """Should return a positive integer for any non-empty text."""
        tokens = count_tokens("Hello world")
        assert tokens > 0

    def test_count_tokens_empty_string(self):
        result = count_tokens("")
        assert result == 0


class TestBudgetCheck:
    def test_under_threshold_no_compact(self):
        pipeline = CompactionPipeline(model_name="gpt-4o", budget_factor=0.85)
        messages = [HumanMessage(content="hello"), AIMessage(content="hi")]
        needs, budget = pipeline.needs_compaction(messages, token_count=1000)
        assert needs is False
        assert budget == int(128_000 * 0.80)

    def test_over_threshold_needs_compact(self):
        pipeline = CompactionPipeline(model_name="gpt-4o", budget_factor=0.85)
        # budget = 128000*0.80 = 102400, threshold = 102400*0.85 = 87040
        # token_count = 90000 > 87040 -> needs compact
        messages = [HumanMessage(content="x" * 100)]
        needs, budget = pipeline.needs_compaction(messages, token_count=90000)
        assert needs is True


class TestModelBudgetMap:
    def test_gpt4o_budget(self):
        pipeline = CompactionPipeline(model_name="gpt-4o")
        assert pipeline.compute_budget() == int(128_000 * 0.80)

    def test_unknown_model_uses_default(self):
        pipeline = CompactionPipeline(model_name="unknown-model")
        assert pipeline.compute_budget() == int(128_000 * 0.80)

    def test_claude_sonnet_budget(self):
        pipeline = CompactionPipeline(model_name="claude-sonnet")
        assert pipeline.compute_budget() == int(200_000 * 0.80)


class TestCheckpoint:
    @pytest.mark.asyncio
    async def test_checkpoint_saves(self, tmp_path: Path):
        pipeline = CompactionPipeline(model_name="gpt-4o", checkpoint_dir=tmp_path)
        messages = [
            SystemMessage(content="You are helpful"),
            HumanMessage(content="Hello"),
            AIMessage(content="Hi there"),
        ]
        cp_id = await pipeline.create_checkpoint(messages, run_id="run-1", step=3)
        assert cp_id is not None
        cp_file = tmp_path / f"{cp_id}.json"
        assert cp_file.exists()

    @pytest.mark.asyncio
    async def test_checkpoint_reloads(self, tmp_path: Path):
        pipeline = CompactionPipeline(model_name="gpt-4o", checkpoint_dir=tmp_path)
        messages = [
            HumanMessage(content="test message"),
            AIMessage(content="test response"),
        ]
        cp_id = await pipeline.create_checkpoint(messages, run_id="run-2", step=1)
        restored = await pipeline.load_checkpoint(cp_id)
        assert len(restored) == 2
        assert restored[0].content == "test message"

    @pytest.mark.asyncio
    async def test_list_checkpoints(self, tmp_path: Path):
        pipeline = CompactionPipeline(model_name="gpt-4o", checkpoint_dir=tmp_path)
        msgs = [HumanMessage(content="test")]
        await pipeline.create_checkpoint(msgs, run_id="abc12345", step=1)
        await pipeline.create_checkpoint(msgs, run_id="def12345", step=2)
        cps = await pipeline.list_checkpoints()
        assert len(cps) == 2


class TestDrop:
    def test_drop_reduces_messages(self):
        pipeline = CompactionPipeline(model_name="gpt-4o")
        messages = [SystemMessage(content="sys")] + [
            HumanMessage(content=f"msg {i}") for i in range(20)
        ]
        summary_text = "Earlier conversation about project setup."
        remaining, dropped = pipeline.drop(messages, summary_text, keep_last=4)
        assert len(remaining) < len(messages)
        # System message kept
        assert any(isinstance(m, SystemMessage) for m in remaining)
        # Summary message inserted
        assert any("Previous conversation summary" in str(m.content) for m in remaining)

    def test_drop_with_no_system(self):
        pipeline = CompactionPipeline(model_name="gpt-4o")
        messages = [HumanMessage(content=f"msg {i}") for i in range(6)]
        remaining, dropped = pipeline.drop(messages, "summary", keep_last=2)
        # Summary + 2 kept
        assert len(remaining) == 3
        assert len(dropped) == 4


class TestDistill:
    @pytest.mark.asyncio
    async def test_distill_appends_to_memory(self, tmp_path: Path):
        memory_file = tmp_path / "MEMORY.md"
        memory_file.write_text("# MEMORY.md\n")

        pipeline = CompactionPipeline(model_name="gpt-4o")
        summary = CompactionSummary(
            summary="Discussed architecture.",
            key_decisions=["Use SQLite"],
            key_facts=["Budget is 10k"],
            open_threads=["API design"],
        )
        await pipeline.distill(summary, memory_file=memory_file)
        content = memory_file.read_text()
        assert "Discussed architecture" in content
        assert "Use SQLite" in content

    @pytest.mark.asyncio
    async def test_distill_creates_memory_file(self, tmp_path: Path):
        memory_file = tmp_path / "subdir" / "MEMORY.md"
        assert not memory_file.exists()

        pipeline = CompactionPipeline(model_name="gpt-4o")
        summary = CompactionSummary(summary="test")
        await pipeline.distill(summary, memory_file=memory_file)
        assert memory_file.exists()


class TestE2E:
    @pytest.mark.asyncio
    async def test_no_compaction_needed(self):
        pipeline = CompactionPipeline(model_name="gpt-4o")
        messages = [HumanMessage(content="hello")]
        result = await pipeline.compact_round(messages, run_id="r1", step=1)
        assert result.was_compacted is False
        assert result.summary is None

    @pytest.mark.asyncio
    async def test_compaction_with_llm_failure_failsafe(self, tmp_path: Path):
        """When LLM summarize fails, should still drop messages without crashing."""
        pipeline = CompactionPipeline(
            model_name="gpt-4o",
            checkpoint_dir=tmp_path,
        )
        # Long messages to exceed the 80% * 0.85 threshold (~87040 tokens)
        long_content = "x" * 10_000  # ~1256 tokens each with tiktoken, 80 * 1256 = ~100480 > 87040
        messages = [SystemMessage(content="sys")] + [
            HumanMessage(content=f"msg {i}: {long_content}") for i in range(80)
        ]
        result = await pipeline.compact_round(messages, run_id="run-1", step=10)
        assert result.was_compacted is True
        assert result.checkpoint_id is not None
        # Even without summary, messages should be reduced
        assert len(result.messages) < len(messages)
        # The drop-only fallback should insert a summary placeholder
        assert any("drop-only" in str(m.content).lower() or "conversation summarized" in str(m.content).lower() for m in result.messages)

    @pytest.mark.asyncio
    async def test_compaction_with_custom_summarize(self, tmp_path: Path):
        """When summarize_fn is provided, it should be called."""
        pipeline = CompactionPipeline(
            model_name="gpt-4o",
            checkpoint_dir=tmp_path,
        )
        long_content = "x" * 10_000
        messages = [SystemMessage(content="sys")] + [
            HumanMessage(content=f"msg {i}: {long_content}") for i in range(80)
        ]

        async def fake_summarize(msgs):
            return CompactionSummary(
                summary="Fake summary",
                key_decisions=["Decision A"],
                key_facts=["Fact B"],
            )

        result = await pipeline.compact_round(
            messages, run_id="run-2", step=5, summarize_fn=fake_summarize
        )
        assert result.was_compacted is True
        assert result.summary is not None
        assert result.summary.key_decisions == ["Decision A"]
        # Summary should be in remaining messages
        assert any("Fake summary" in str(m.content) for m in result.messages)
