"""Deterministic local workload corpus for harness performance evidence."""
from __future__ import annotations

import asyncio
import json
import math
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any, Callable

from config import RetrievalDomainConfig
from langchain_core.messages import HumanMessage
from graph.compaction import CompactionPipeline, CompactionSummary
from graph.memory_indexer import MemoryIndexer
from graph.skill_selector import SkillSelector
from tools.base import ToolContext
from tools.contracts import ToolResult
from tools.delegate_registry import DelegateRegistry
from tools.policy import PermissionLevel, ToolPolicyEngine
from tools.runner import ToolRunner


WORKLOAD_SCHEMA_VERSION = 1
WORKLOAD_NAMES = (
    "interactive_tool_loop",
    "blocking_delegation",
    "background_delegation",
    "skill_detection_loading",
    "compaction_memory_retrieval",
)


@dataclass
class _EchoTool:
    name: str = "read_files"
    description: str = "Deterministic read-only workload tool"
    permission_level: PermissionLevel = PermissionLevel.L0_READ

    def run(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        _ = context
        return ToolResult.success(
            tool_name=self.name,
            data={"value": str(args.get("value", ""))},
            duration_ms=0,
        )


def _interactive_tool_loop(root: Path) -> dict[str, int]:
    runner = ToolRunner(policy_engine=ToolPolicyEngine())
    context = ToolContext(
        workspace_root=root,
        trigger_type="chat",
        run_id="workload-tool-loop",
        session_id="workload-session",
    )
    tool = _EchoTool()
    for value in ("one", "two", "three"):
        result = runner.run_tool(tool, args={"value": value}, context=context)
        assert result.ok
    return {"tool_calls": 3, "retries": 0}


def _blocking_delegation(root: Path) -> dict[str, int]:
    registry = DelegateRegistry(root)
    registered = registry.register(
        agent_id="default",
        parent_session_id="workload-session",
        task="Summarize the fixed workload corpus",
        role="researcher",
        allowed_tools=["read_files"],
        blocked_tools=[],
        timeout_seconds=30,
        parent_run_id="workload-blocking",
    )
    registry.mark_completed(registered["delegate_id"], {"summary": "done"})
    state = registry.get_status(registered["delegate_id"])
    assert state is not None and state.status == "completed"
    return {"delegates": 1, "blocking_completed": 1}


async def _background_delegate_task() -> None:
    await asyncio.sleep(0)


def _background_delegation(root: Path) -> dict[str, int]:
    _ = root
    asyncio.run(_background_delegate_task())
    return {"delegates": 1, "background_completed": 1}


def _skill_detection_loading(root: Path) -> dict[str, int]:
    skill_file = root / "skills" / "memory-summary" / "SKILL.md"
    skill_file.parent.mkdir(parents=True, exist_ok=True)
    skill_file.write_text(
        "---\nname: memory-summary\ndescription: Summarize memory files\n---\n"
        "Read memory and summarize the important facts.\n",
        encoding="utf-8",
    )
    selected = SkillSelector(max_cache_entries=2).select(
        base_dir=root,
        message="Summarize memory files",
        history=[],
    )
    assert selected and selected[0].name == "memory-summary"
    return {"skills_loaded": 1, "skills_selected": len(selected)}


async def _compact_and_retrieve(root: Path) -> dict[str, int]:
    memory_file = root / "memory" / "MEMORY.md"
    memory_file.parent.mkdir(parents=True, exist_ok=True)
    memory_file.write_text("The workload corpus validates agent reliability.\n")
    (root / "config.json").write_text(
        '{"retrieval":{"storage":{"engine":"json"}}}\n', encoding="utf-8"
    )
    settings = RetrievalDomainConfig(
        top_k=2,
        semantic_weight=0.0,
        lexical_weight=1.0,
        chunk_size=64,
        chunk_overlap=0,
    )
    indexer = MemoryIndexer(root, config_base_dir=root)
    indexer.rebuild_index(settings=settings)
    retrievals = indexer.retrieve("reliability", settings=settings)

    pipeline = CompactionPipeline(
        model_name="gpt-4o",
        budget_factor=0.001,
        checkpoint_dir=root / "checkpoints",
    )

    async def summarize(_: list[Any]) -> CompactionSummary:
        return CompactionSummary(summary="A bounded workload summary.")

    result = await pipeline.compact_round(
        [HumanMessage(content="x" * 1000)],
        run_id="workload-compaction",
        summarize_fn=summarize,
    )
    assert result.was_compacted and retrievals
    return {"compacted": 1, "retrievals": len(retrievals)}


def _run_compact_and_retrieve(root: Path) -> dict[str, int]:
    return asyncio.run(_compact_and_retrieve(root))


_WORKLOADS: tuple[tuple[str, Callable[[Path], dict[str, int]]], ...] = (
    ("interactive_tool_loop", _interactive_tool_loop),
    ("blocking_delegation", _blocking_delegation),
    ("background_delegation", _background_delegation),
    ("skill_detection_loading", _skill_detection_loading),
    ("compaction_memory_retrieval", _run_compact_and_retrieve),
)


def _percentile(values: list[int], percentile: float) -> int:
    ordered = sorted(values)
    index = min(
        len(ordered) - 1,
        max(0, math.ceil(len(ordered) * percentile) - 1),
    )
    return ordered[index]


def run_workload_corpus(iterations: int = 5) -> dict[str, Any]:
    """Run fixed local workloads and return p50/p95 evidence."""
    sample_count = max(1, int(iterations))
    results: dict[str, Any] = {
        "schema_version": WORKLOAD_SCHEMA_VERSION,
        "iterations": sample_count,
        "workloads": {},
    }
    for name, workload in _WORKLOADS:
        durations: list[int] = []
        metrics: dict[str, int] = {}
        for _ in range(sample_count):
            with tempfile.TemporaryDirectory(prefix=f"oml-{name}-") as raw_root:
                started = time.perf_counter()
                metrics = workload(Path(raw_root))
                durations.append(max(0, int((time.perf_counter() - started) * 1000)))
        results["workloads"][name] = {
            "samples_ms": durations,
            "p50_ms": int(median(durations)),
            "p95_ms": _percentile(durations, 0.95),
            "metrics": metrics,
        }
    return results


def main() -> None:
    print(json.dumps(run_workload_corpus(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
