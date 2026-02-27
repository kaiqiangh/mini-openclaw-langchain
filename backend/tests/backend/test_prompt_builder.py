from __future__ import annotations

import time

from config import InjectionMode, RuntimeConfig
from graph.prompt_builder import PromptBuilder


def test_prompt_builder_truncation_and_missing_marker(backend_base_dir):
    (backend_base_dir / "workspace" / "USER.md").write_text("x" * 200, encoding="utf-8")
    (backend_base_dir / "workspace" / "HEARTBEAT.md").unlink(missing_ok=True)

    runtime = RuntimeConfig(
        injection_mode=InjectionMode.EVERY_TURN,
        bootstrap_max_chars=40,
        bootstrap_total_max_chars=10000,
    )

    pack = PromptBuilder().build_system_prompt(
        base_dir=backend_base_dir,
        runtime=runtime,
        rag_mode=False,
        is_first_turn=True,
    )

    assert "...[truncated]" in pack.prompt
    assert "[MISSING FILE: workspace/HEARTBEAT.md]" in pack.prompt


def test_prompt_builder_cache_digest_changes_when_source_changes(backend_base_dir):
    builder = PromptBuilder()
    runtime = RuntimeConfig(injection_mode=InjectionMode.EVERY_TURN)

    first = builder.build_system_prompt(
        base_dir=backend_base_dir,
        runtime=runtime,
        rag_mode=False,
        is_first_turn=True,
    )

    second = builder.build_system_prompt(
        base_dir=backend_base_dir,
        runtime=runtime,
        rag_mode=False,
        is_first_turn=True,
    )
    assert first.digest == second.digest

    time.sleep(0.02)
    path = backend_base_dir / "workspace" / "AGENTS.md"
    path.write_text("AGENTS UPDATED", encoding="utf-8")

    third = builder.build_system_prompt(
        base_dir=backend_base_dir,
        runtime=runtime,
        rag_mode=False,
        is_first_turn=True,
    )
    assert third.digest != first.digest
