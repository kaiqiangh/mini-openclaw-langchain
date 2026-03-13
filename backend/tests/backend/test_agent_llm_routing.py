from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from langchain_core.messages import AIMessageChunk

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


class _StubToolCapableModel:
    def __init__(self, profile_name: str) -> None:
        self.profile_name = profile_name

    def bind_tools(self, tools):  # type: ignore[no-untyped-def]
        _ = tools
        return self

    async def ainvoke(self, input, config=None, **kwargs):  # type: ignore[no-untyped-def]
        _ = input, config, kwargs
        return None

    async def astream(self, input, config=None, **kwargs):  # type: ignore[no-untyped-def]
        _ = input, config, kwargs
        if False:
            yield None


class _ProfileAwareChain:
    def __init__(
        self,
        *,
        model: _StubToolCapableModel,
        behaviors: dict[str, list[object] | object],
        call_order: list[str],
    ) -> None:
        self.model = model
        self.behaviors = behaviors
        self.call_order = call_order

    async def astream(self, payload, config=None):  # type: ignore[no-untyped-def]
        _ = payload, config
        self.call_order.append(self.model.profile_name)
        scripted = self.behaviors[self.model.profile_name]
        if isinstance(scripted, list):
            outcome = scripted.pop(0)
        else:
            outcome = scripted
        if isinstance(outcome, Exception):
            raise outcome
        yield AIMessageChunk(content=str(outcome))


def _patch_agent_execution(
    monkeypatch,
    manager: AgentManager,
    behaviors: dict[str, list[object] | object],
    call_order: list[str],
) -> None:
    monkeypatch.setattr(
        manager.runtime_services,
        "get_runtime_llm",
        lambda runtime, profile: _StubToolCapableModel(profile.profile_name),
    )
    monkeypatch.setattr(
        manager.lcel_pipelines,
        "model_chain",
        lambda **kwargs: _ProfileAwareChain(
            model=kwargs["llm"],
            behaviors=behaviors,
            call_order=call_order,
        ),
    )


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

    manager = AgentManager()
    manager.initialize(tmp_path)
    call_order: list[str] = []
    _patch_agent_execution(
        monkeypatch,
        manager,
        {"openai": "openai-success", "deepseek": "deepseek-success"},
        call_order,
    )

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

    manager = AgentManager()
    manager.initialize(tmp_path)
    call_order: list[str] = []
    _patch_agent_execution(
        monkeypatch,
        manager,
        {
            "openai": [_RateLimitFailure("rate limited")],
            "azure_foundry": "azure-success",
        },
        call_order,
    )

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

    manager = AgentManager()
    manager.initialize(tmp_path)
    call_order: list[str] = []
    _patch_agent_execution(
        monkeypatch,
        manager,
        {
            "openai": [_RateLimitFailure("openai limited")],
            "deepseek": [_RateLimitFailure("deepseek limited")],
            "azure_foundry": "azure-success",
        },
        call_order,
    )

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
