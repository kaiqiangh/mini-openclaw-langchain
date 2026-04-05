from __future__ import annotations

import json
from pathlib import Path

from langchain_core.messages import AIMessage

from config import load_runtime_config
from graph.agent import AgentManager
from graph.callbacks import AuditCallbackHandler, UsageCaptureCallbackHandler
from graph.tool_execution import ToolExecutionService
from storage.run_store import AuditStore
from storage.usage_store import UsageQuery


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True) + "\n", encoding="utf-8")


def _seed_base(base_dir: Path, root_config: dict | None = None) -> None:
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
    _write_json(
        base_dir / "config.json",
        root_config
        or {"llm_defaults": {"default": "openai", "fallbacks": []}},
    )


def test_runtime_execution_services_build_callbacks(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    _seed_base(tmp_path)

    manager = AgentManager()
    manager.initialize(tmp_path)
    runtime = manager.get_runtime("default")

    bundle = manager.runtime_services.build_callbacks(
        run_id="run-1",
        session_id="session-1",
        trigger_type="chat",
        runtime_root=runtime.root_dir,
        runtime_audit_store=runtime.audit_store,
    )

    assert len(bundle.callbacks) >= 2
    assert isinstance(bundle.callbacks[0], AuditCallbackHandler)
    assert isinstance(bundle.usage_capture, UsageCaptureCallbackHandler)
    assert bundle.callbacks[1] is bundle.usage_capture


def test_runtime_execution_services_appends_route_audit_event(
    monkeypatch, tmp_path: Path
):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    _seed_base(tmp_path)

    manager = AgentManager()
    manager.initialize(tmp_path)
    runtime = manager.get_runtime("default")

    manager.runtime_services.append_llm_route_event(
        runtime=runtime,
        run_id="run-2",
        session_id="session-2",
        trigger_type="chat",
        event="llm_route_resolved",
        details={"profile": "openai", "attempt": 1},
    )

    rows = [
        json.loads(line)
        for line in runtime.audit_store.steps_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert rows[-1]["event"] == "llm_route_resolved"
    assert rows[-1]["details"]["profile"] == "openai"


def test_runtime_execution_services_resolves_tool_capable_model(
    monkeypatch, tmp_path: Path
):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    _seed_base(tmp_path)

    manager = AgentManager()
    manager.initialize(tmp_path)
    runtime = manager.get_runtime("default")
    route = manager.runtime_services.resolve_llm_route(runtime)

    model, selected_model = manager.runtime_services.resolve_tool_capable_model(
        runtime=runtime,
        candidate=route.candidates[0],
        has_tools=False,
        tool_loop_model=route.tool_loop_model,
        tool_loop_model_overrides=route.tool_loop_model_overrides,
    )

    assert selected_model == route.candidates[0].profile.model
    assert hasattr(model, "bind_tools")


def test_runtime_execution_services_records_usage(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    _seed_base(tmp_path)

    manager = AgentManager()
    manager.initialize(tmp_path)
    runtime = manager.get_runtime("default")

    usage_message = AIMessage(
        content="hello",
        usage_metadata={"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
        response_metadata={
            "model_name": "gpt-4o-mini",
            "token_usage": {
                "prompt_tokens": 10,
                "completion_tokens": 2,
                "total_tokens": 12,
            },
        },
    )

    usage_state = manager.runtime_services.initial_usage_state(
        provider="openai",
        model="gpt-4o-mini",
    )
    usage_sources: dict[str, dict[str, int]] = {}

    changed = manager.runtime_services.accumulate_usage_from_messages(
        usage_state=usage_state,
        usage_sources=usage_sources,
        messages=[usage_message],
        source_prefix="llm_end:run-3",
        fallback_model="gpt-4o-mini",
    )

    payload = manager.runtime_services.record_usage(
        usage=usage_state,
        run_id="run-3",
        session_id="session-3",
        trigger_type="chat",
        agent_id="default",
        usage_store=runtime.usage_store,
    )

    assert changed is True
    assert usage_state["total_tokens"] == 12
    assert payload["total_tokens"] == 12
    rows = runtime.usage_store.query_records(query=UsageQuery(limit=10))
    assert rows
    assert rows[-1]["run_id"] == "run-3"


def test_tool_execution_service_build_honors_explicit_delegate_scope(
    tmp_path: Path,
):
    _seed_base(tmp_path)
    runtime = load_runtime_config(tmp_path / "config.json")

    service = ToolExecutionService.build(
        config_base_dir=tmp_path,
        runtime_root=tmp_path,
        runtime=runtime,
        trigger_type="chat",
        agent_id="default",
        run_id="run-1",
        session_id="session-1",
        runtime_audit_store=AuditStore(tmp_path),
        explicit_enabled_tools=["terminal"],
        explicit_blocked_tools=[],
    )

    assert [tool.name for tool in service.tools] == ["terminal"]
