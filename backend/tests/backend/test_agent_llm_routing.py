from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from graph.agent import AgentManager


class _RateLimitFailure(Exception):
    status_code = 429


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True) + "\n", encoding="utf-8")


def _seed_base(base_dir: Path, root_config: dict) -> None:
    for rel in ("workspace", "memory", "knowledge", "skills", "storage", "workspaces"):
        (base_dir / rel).mkdir(parents=True, exist_ok=True)
    for name in (
        "AGENTS.md",
        "SOUL.md",
        "IDENTITY.md",
        "USER.md",
        "HEARTBEAT.md",
        "BOOTSTRAP.md",
    ):
        (base_dir / "workspace" / name).write_text(f"# {name}\n", encoding="utf-8")
    (base_dir / "memory" / "MEMORY.md").write_text("# MEMORY\n", encoding="utf-8")
    _write_json(base_dir / "config.json", root_config)


def _configure_agent(base_dir: Path, agent_id: str, payload: dict) -> None:
    root = base_dir / "workspaces" / agent_id
    root.mkdir(parents=True, exist_ok=True)
    _write_json(root / "config.json", payload)


def _patch_agent_execution(
    monkeypatch,
    behaviors: dict[str, list[object] | object],
    call_order: list[str],
) -> None:
    def fake_get_runtime_llm(self, runtime, profile):  # type: ignore[no-untyped-def]
        _ = self, runtime, profile
        return object()

    def fake_build_agent(self, **kwargs):  # type: ignore[no-untyped-def]
        profile = kwargs["llm_profile"]
        call_order.append(profile.profile_name)
        scripted = behaviors[profile.profile_name]

        class _FakeAgent:
            async def ainvoke(self, payload, config):  # type: ignore[no-untyped-def]
                _ = payload, config
                if isinstance(scripted, list):
                    outcome = scripted.pop(0)
                else:
                    outcome = scripted
                if isinstance(outcome, Exception):
                    raise outcome
                return {"messages": [SimpleNamespace(content=str(outcome))]}

        return _FakeAgent(), profile.model or profile.profile_name

    monkeypatch.setattr(AgentManager, "_get_runtime_llm", fake_get_runtime_llm)
    monkeypatch.setattr(AgentManager, "_build_agent", fake_build_agent)


def _load_audit_events(path: Path) -> list[str]:
    if not path.exists():
        return []
    events: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        events.append(json.loads(line)["event"])
    return events


def test_agent_runs_are_isolated_when_default_credentials_are_missing(
    monkeypatch, tmp_path: Path
):
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    _seed_base(
        tmp_path,
        {"llm_defaults": {"default": "openai", "fallbacks": []}},
    )
    _configure_agent(tmp_path, "main", {"llm": {"default": "deepseek"}})
    _configure_agent(tmp_path, "elon", {"llm": {"default": "openai"}})

    call_order: list[str] = []
    _patch_agent_execution(
        monkeypatch,
        {"openai": "openai-success", "deepseek": "deepseek-success"},
        call_order,
    )

    manager = AgentManager()
    manager.initialize(tmp_path)

    elon_result = asyncio.run(
        manager.run_once(
            message="hello",
            history=[],
            session_id="session-elon",
            agent_id="elon",
        )
    )
    assert elon_result["text"] == "openai-success"

    with pytest.raises(RuntimeError, match="missing DEEPSEEK_API_KEY"):
        asyncio.run(
            manager.run_once(
                message="hello",
                history=[],
                session_id="session-main",
                agent_id="main",
            )
        )

    assert call_order == ["openai"]


def test_run_once_skips_unavailable_fallbacks_and_uses_next_available_profile(
    monkeypatch, tmp_path: Path
):
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("AZURE_FOUNDRY_API_KEY", "azure-key")
    monkeypatch.setenv("AZURE_FOUNDRY_BASE_URL", "https://example.foundry.azure.com")

    _seed_base(
        tmp_path,
        {
            "agent_runtime": {"max_retries": 0},
            "llm_defaults": {
                "default": "openai",
                "fallbacks": ["deepseek", "azure_foundry"],
            }
        },
    )

    call_order: list[str] = []
    _patch_agent_execution(
        monkeypatch,
        {
            "openai": [_RateLimitFailure("rate limited")],
            "azure_foundry": "azure-success",
        },
        call_order,
    )

    manager = AgentManager()
    manager.initialize(tmp_path)

    result = asyncio.run(
        manager.run_once(
            message="hello",
            history=[],
            session_id="session-default",
            agent_id="default",
        )
    )

    assert result["text"] == "azure-success"
    assert call_order == ["openai", "azure_foundry"]

    steps_path = manager.get_runtime("default").audit_store.steps_file
    events = _load_audit_events(steps_path)
    assert "llm_route_skipped" in events
    assert "llm_fallback_attempt" in events
    assert "llm_fallback_selected" in events


def test_fallback_order_is_respected_across_multiple_candidates(
    monkeypatch, tmp_path: Path
):
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    monkeypatch.setenv("AZURE_FOUNDRY_API_KEY", "azure-key")
    monkeypatch.setenv("AZURE_FOUNDRY_BASE_URL", "https://example.foundry.azure.com")

    _seed_base(
        tmp_path,
        {
            "agent_runtime": {"max_retries": 0},
            "llm_defaults": {
                "default": "openai",
                "fallbacks": ["deepseek", "azure_foundry"],
            }
        },
    )

    call_order: list[str] = []
    _patch_agent_execution(
        monkeypatch,
        {
            "openai": [_RateLimitFailure("openai limited")],
            "deepseek": [_RateLimitFailure("deepseek limited")],
            "azure_foundry": "azure-success",
        },
        call_order,
    )

    manager = AgentManager()
    manager.initialize(tmp_path)

    result = asyncio.run(
        manager.run_once(
            message="hello",
            history=[],
            session_id="session-order",
            agent_id="default",
        )
    )

    assert result["text"] == "azure-success"
    assert call_order == ["openai", "deepseek", "azure_foundry"]


def test_list_agents_reports_invalid_llm_routes_without_blocking_other_agents(
    monkeypatch, tmp_path: Path
):
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")

    _seed_base(
        tmp_path,
        {"llm_defaults": {"default": "openai", "fallbacks": []}},
    )
    _configure_agent(tmp_path, "broken", {"llm": {"default": "missing-profile"}})
    _configure_agent(tmp_path, "healthy", {"llm": {"default": "openai"}})

    manager = AgentManager()
    manager.initialize(tmp_path)

    rows = {row["agent_id"]: row for row in manager.list_agents()}
    assert rows["healthy"]["llm_status"]["valid"] is True
    assert rows["healthy"]["llm_status"]["runnable"] is True
    assert rows["broken"]["llm_status"]["valid"] is False
    assert "missing-profile" in " ".join(rows["broken"]["llm_status"]["errors"])
