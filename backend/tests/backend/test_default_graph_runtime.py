from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.runnables import RunnableLambda
from langgraph.types import Command

from graph.agent import AgentManager
from graph.lcel_pipelines import RuntimeLcelPipelines
from graph.runtime_execution_services import RuntimeCallbackBundle
from graph.runtime_types import (
    BlockingDelegateRef,
    ResolvedDelegateResult,
    RuntimeRequest,
)
from graph.skill_selector import SelectedSkill
from graph.tool_execution import ToolExecutionService
from tools import delegate_tool as delegate_tool_module
from tools.contracts import ToolResult
from tools.delegate_registry import DelegateRegistry


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
    (base_dir / "memory" / "MEMORY.md").write_text("# MEMORY\nhello world\n", encoding="utf-8")
    _write_json(
        base_dir / "config.json",
        root_config
        or {"llm_defaults": {"default": "openai", "fallbacks": []}},
    )


class _ScriptedChain:
    def __init__(self, scripts: list[list[AIMessageChunk]]) -> None:
        self.scripts = scripts

    async def astream(self, payload, config=None):  # type: ignore[no-untyped-def]
        _ = payload, config
        if not self.scripts:
            return
        current = self.scripts.pop(0)
        for chunk in current:
            yield chunk


class _RetryingChain:
    def __init__(self, outcomes: list[Exception | list[AIMessageChunk]]) -> None:
        self.outcomes = outcomes

    async def astream(self, payload, config=None):  # type: ignore[no-untyped-def]
        _ = payload, config
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        for chunk in outcome:
            yield chunk


class _CapturingChain:
    def __init__(self, captured: dict[str, Any], chunks: list[AIMessageChunk]) -> None:
        self.captured = captured
        self.chunks = chunks

    async def astream(self, payload, config=None):  # type: ignore[no-untyped-def]
        self.captured["payload"] = payload
        self.captured["config"] = config
        for chunk in self.chunks:
            yield chunk


class _RecordingScriptedChain:
    def __init__(
        self,
        payloads: list[dict[str, Any]],
        scripts: list[list[AIMessageChunk]],
    ) -> None:
        self.payloads = payloads
        self.scripts = scripts

    async def astream(self, payload, config=None):  # type: ignore[no-untyped-def]
        _ = config
        self.payloads.append(payload)
        current = self.scripts.pop(0)
        for chunk in current:
            yield chunk


class _StubToolCapableModel:
    def __init__(self, profile_name: str = "stub") -> None:
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


class _DummyTool:
    name = "dummy"

    async def ainvoke(self, args):  # type: ignore[no-untyped-def]
        return json.dumps(
            asdict(
                ToolResult.success(
                    tool_name=self.name,
                    data={"echo": args},
                    duration_ms=7,
                )
            ),
            ensure_ascii=False,
        )


def test_runtime_lcel_model_chain_injects_system_prompt_and_messages():
    pipelines = RuntimeLcelPipelines()
    chain = pipelines.model_chain(llm=RunnableLambda(lambda messages: messages), tools=[])

    result = chain.invoke(
        {
            "system_prompt": "system",
            "messages": [HumanMessage(content="hello")],
        }
    )

    assert len(result) == 2
    assert isinstance(result[0], SystemMessage)
    assert result[0].content == "system"
    assert isinstance(result[1], HumanMessage)
    assert result[1].content == "hello"


def test_runtime_lcel_message_chain_normalizes_history_and_rag_context():
    pipelines = RuntimeLcelPipelines()
    result = pipelines.message_chain().invoke(
        {
            "history": [
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": "second"},
            ],
            "rag_context": "remembered fact",
            "message": "third",
        }
    )

    assert [type(item) for item in result] == [HumanMessage, AIMessage, SystemMessage, HumanMessage]
    assert result[2].content == "remembered fact"
    assert result[3].content == "third"


def test_runtime_lcel_system_prompt_chain_prefixes_selected_skills():
    pipelines = RuntimeLcelPipelines()
    result = pipelines.system_prompt_chain().invoke(
        {
            "base_system_prompt": "core prompt",
            "selected_skills": [
                SelectedSkill(
                    name="weather-helper",
                    location="./skills/weather-helper/SKILL.md",
                    description="Weather helper",
                    reason="matched terms: weather",
                    score=10,
                )
            ],
        }
    )

    assert "[Selected Skills For This Request]" in result
    assert "weather-helper" in result
    assert result.endswith("core prompt")


def test_tool_execution_service_normalizes_tool_results():
    service = ToolExecutionService(
        tools=[_DummyTool()],
        tools_by_name={"dummy": _DummyTool()},
    )

    envelopes, tool_messages = asyncio.run(
        service.execute_pending(
            [{"id": "call-1", "name": "dummy", "args": {"path": "memory/MEMORY.md"}}]
        )
    )

    assert len(envelopes) == 1
    assert envelopes[0].tool == "dummy"
    assert envelopes[0].ok is True
    assert envelopes[0].duration_ms == 7
    assert "memory/MEMORY.md" in envelopes[0].output
    assert tool_messages[0].tool_call_id == "call-1"
    assert tool_messages[0].status == "success"


def test_tool_step_executes_delegate_status_when_delegate_tools_are_available(
    tmp_path: Path,
):
    _seed_base(tmp_path)
    manager = AgentManager()
    manager.initialize(tmp_path)
    registry = DelegateRegistry(base_dir=tmp_path)
    manager.runtime_services.delegate_registry = registry

    request = RuntimeRequest(
        message="check delegate",
        history=[],
        session_id="sess-1",
        trigger_type="chat",
        agent_id="default",
    )
    registration = registry.register(
        "default",
        "sess-1",
        "Summarize the workspace",
        "researcher",
        ["read_files"],
        [],
        60,
    )

    graph = manager._runtime_graph()
    result = asyncio.run(
        graph._tool_step(
            {
                "request": request,
                "run_id": "run-1",
                "pending_tool_calls": [
                    {
                        "id": "call-1",
                        "name": "delegate_status",
                        "args": {"delegate_id": registration["delegate_id"]},
                    }
                ],
                "model_messages": [],
            }
        )
    )

    assert len(result["tool_history"]) == 1
    assert result["tool_history"][0].tool == "delegate_status"
    assert result["tool_history"][0].ok is True
    assert result["tool_history"][0].error_code != "E_NOT_FOUND"
    assert registration["delegate_id"] in result["tool_history"][0].output


def test_tool_step_waits_for_blocking_delegate_result(monkeypatch, tmp_path: Path):
    _seed_base(tmp_path)
    manager = AgentManager()
    manager.initialize(tmp_path)
    runtime = manager.get_runtime("default")
    runtime.runtime_config.delegation.enabled = True
    runtime.runtime_config.delegation.allowed_tool_scopes = {
        "researcher": ["read_files"],
    }
    manager.runtime_services.delegate_registry = DelegateRegistry(base_dir=tmp_path)
    graph = manager._runtime_graph()

    class _ChildRuntime:
        async def invoke(self, request):  # type: ignore[no-untyped-def]
            await asyncio.sleep(0.05)
            return SimpleNamespace(
                messages=[SimpleNamespace(type="assistant", content="Delegated answer")],
                token_usage={"prompt_tokens": 1, "completion_tokens": 1},
            )

        async def aget_state(self, request):  # type: ignore[no-untyped-def]
            return {}

    monkeypatch.setattr(delegate_tool_module, "_DELEGATE_INLINE_WAIT_SECONDS", 0.01)
    monkeypatch.setattr(manager.graph_registry, "resolve", lambda name: _ChildRuntime())

    request = RuntimeRequest(
        message="delegate this task",
        history=[],
        session_id="session-blocking",
        trigger_type="chat",
        agent_id="default",
    )
    result = asyncio.run(
        graph._tool_step(
            {
                "request": request,
                "run_id": "run-blocking",
                "pending_tool_calls": [
                    {
                        "id": "call-1",
                        "name": "delegate",
                        "args": {
                            "task": "Review memory",
                            "role": "researcher",
                            "allowed_tools": ["read_files"],
                            "wait_for_result": True,
                        },
                    }
                ],
                "model_messages": [],
                "resolved_delegate_results": [],
            }
        )
    )

    assert isinstance(result, Command)
    assert result.goto == "wait_for_delegates"
    assert result.update["delegate_waiting"] is True
    assert len(result.update["tool_history"]) == 1
    assert result.update["tool_history"][0].tool == "delegate"
    assert result.update["tool_history"][0].ok is True
    assert '"ok": true' in result.update["tool_history"][0].output
    pending = result.update["pending_blocking_delegates"]
    assert len(pending) == 1
    assert pending[0].task == "Review memory"


def test_tool_step_keeps_non_blocking_delegate_in_normal_tool_flow(
    monkeypatch,
    tmp_path: Path,
):
    _seed_base(tmp_path)
    manager = AgentManager()
    manager.initialize(tmp_path)
    runtime = manager.get_runtime("default")
    runtime.runtime_config.delegation.enabled = True
    runtime.runtime_config.delegation.allowed_tool_scopes = {
        "researcher": ["read_files"],
    }
    manager.runtime_services.delegate_registry = DelegateRegistry(base_dir=tmp_path)
    graph = manager._runtime_graph()

    class _ChildRuntime:
        async def invoke(self, request):  # type: ignore[no-untyped-def]
            return SimpleNamespace(
                messages=[SimpleNamespace(type="assistant", content="Delegated answer")],
                token_usage={"prompt_tokens": 1, "completion_tokens": 1},
            )

        async def aget_state(self, request):  # type: ignore[no-untyped-def]
            return {}

        async def aupdate_state(self, request, values):  # type: ignore[no-untyped-def]
            _ = request, values
            return {}

    monkeypatch.setattr(delegate_tool_module, "_DELEGATE_INLINE_WAIT_SECONDS", 0.01)
    monkeypatch.setattr(manager.graph_registry, "resolve", lambda name: _ChildRuntime())

    request = RuntimeRequest(
        message="delegate this task",
        history=[],
        session_id="session-non-blocking",
        trigger_type="chat",
        agent_id="default",
    )
    result = asyncio.run(
        graph._tool_step(
            {
                "request": request,
                "run_id": "run-non-blocking",
                "pending_tool_calls": [
                    {
                        "id": "call-1",
                        "name": "delegate",
                        "args": {
                            "task": "Review memory",
                            "role": "researcher",
                            "allowed_tools": ["read_files"],
                            "wait_for_result": False,
                        },
                    }
                ],
                "model_messages": [],
                "resolved_delegate_results": [],
            }
        )
    )

    assert not isinstance(result, Command)
    assert result["pending_new_response"] is True
    assert len(result["tool_history"]) == 1
    assert result["tool_history"][0].tool == "delegate"
    assert result["tool_history"][0].ok is True
    assert '"ok": true' in result["tool_history"][0].output


def test_tool_step_denies_sibling_business_tools_for_blocking_delegate(
    monkeypatch,
    tmp_path: Path,
):
    _seed_base(tmp_path)
    manager = AgentManager()
    manager.initialize(tmp_path)
    runtime = manager.get_runtime("default")
    runtime.runtime_config.delegation.enabled = True
    runtime.runtime_config.delegation.allowed_tool_scopes = {
        "researcher": ["read_files"],
    }
    manager.runtime_services.delegate_registry = DelegateRegistry(base_dir=tmp_path)
    graph = manager._runtime_graph()

    class _ChildRuntime:
        async def invoke(self, request):  # type: ignore[no-untyped-def]
            await asyncio.sleep(0.05)
            return SimpleNamespace(
                messages=[SimpleNamespace(type="assistant", content="Delegated answer")],
                token_usage={"prompt_tokens": 1, "completion_tokens": 1},
            )

        async def aget_state(self, request):  # type: ignore[no-untyped-def]
            return {}

    monkeypatch.setattr(delegate_tool_module, "_DELEGATE_INLINE_WAIT_SECONDS", 0.01)
    monkeypatch.setattr(manager.graph_registry, "resolve", lambda name: _ChildRuntime())

    request = RuntimeRequest(
        message="delegate this task",
        history=[],
        session_id="session-blocking-tools",
        trigger_type="chat",
        agent_id="default",
    )
    result = asyncio.run(
        graph._tool_step(
            {
                "request": request,
                "run_id": "run-blocking-tools",
                "pending_tool_calls": [
                    {
                        "id": "call-1",
                        "name": "delegate",
                        "args": {
                            "task": "Review memory",
                            "role": "researcher",
                            "allowed_tools": ["read_files"],
                            "wait_for_result": True,
                        },
                    },
                    {
                        "id": "call-2",
                        "name": "read_files",
                        "args": {"path": "memory/MEMORY.md"},
                    },
                ],
                "model_messages": [],
                "resolved_delegate_results": [],
            }
        )
    )

    assert isinstance(result, Command)
    denied = [
        envelope
        for envelope in result.update["tool_history"]
        if envelope.tool == "read_files"
    ]
    assert len(denied) == 1
    assert denied[0].error_code == "E_POLICY_DENIED"
    assert "blocking delegate" in denied[0].error_message


def test_wait_for_delegates_waits_until_all_blocking_delegates_finish(
    monkeypatch,
    tmp_path: Path,
):
    _seed_base(tmp_path)
    manager = AgentManager()
    manager.initialize(tmp_path)
    graph = manager._runtime_graph()

    pending = [
        BlockingDelegateRef(
            delegate_id="del_a",
            role="researcher",
            task="Summarize memory",
            sub_session_id="sub_a",
        ),
        BlockingDelegateRef(
            delegate_id="del_b",
            role="researcher",
            task="Summarize knowledge",
            sub_session_id="sub_b",
        ),
    ]
    resolved_a = ResolvedDelegateResult(
        delegate_id="del_a",
        role="researcher",
        task="Summarize memory",
        status="completed",
        result_summary="Memory done",
        tools_used=["read_files"],
        duration_ms=24,
        error_message=None,
    )
    resolved_b = ResolvedDelegateResult(
        delegate_id="del_b",
        role="researcher",
        task="Summarize knowledge",
        status="timeout",
        result_summary="",
        tools_used=["read_files"],
        duration_ms=120_000,
        error_message="delegate timed out",
    )
    existing = ResolvedDelegateResult(
        delegate_id="del_existing",
        role="researcher",
        task="Prior work",
        status="completed",
        result_summary="Already injected",
        tools_used=["read_files"],
        duration_ms=12,
        error_message=None,
    )

    call_counts: dict[str, int] = {}
    sleep_calls: list[float] = []

    def _materialize(ref: BlockingDelegateRef) -> ResolvedDelegateResult | None:
        count = call_counts.get(ref.delegate_id, 0) + 1
        call_counts[ref.delegate_id] = count
        if ref.delegate_id == "del_b" and count == 1:
            return None
        if ref.delegate_id == "del_a":
            return resolved_a
        return resolved_b

    async def _fast_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr(graph, "_materialize_delegate_result", _materialize)
    monkeypatch.setattr(asyncio, "sleep", _fast_sleep)

    result = asyncio.run(
        graph._wait_for_delegates(
            {
                "run_id": "run-wait-all",
                "pending_blocking_delegates": pending,
                "resolved_delegate_results": [existing],
            }
        )
    )

    assert result["pending_blocking_delegates"] == []
    assert result["delegate_waiting"] is False
    assert result["pending_delegate_result_injection"] == [resolved_a, resolved_b]
    assert result["resolved_delegate_results"] == [existing, resolved_a, resolved_b]
    assert call_counts == {"del_a": 2, "del_b": 2}
    assert sleep_calls == [0.1]


def test_compose_inputs_injects_blocking_delegate_results(tmp_path: Path):
    _seed_base(tmp_path)
    manager = AgentManager()
    manager.initialize(tmp_path)
    graph = manager._runtime_graph()

    composed = graph._compose_inputs(
        {
            "base_system_prompt": "base prompt",
            "selected_skill_items": [],
            "messages": [],
            "model_messages": [],
            "compressed_context": "",
            "rag_context": None,
            "resolved_delegate_results": [
                ResolvedDelegateResult(
                    delegate_id="del_1234",
                    role="researcher",
                    task="Summarize memory",
                    status="completed",
                    result_summary="Delegated summary",
                    tools_used=["read_files"],
                    duration_ms=24,
                    error_message=None,
                )
            ],
            "pending_delegate_result_injection": [
                ResolvedDelegateResult(
                    delegate_id="del_1234",
                    role="researcher",
                    task="Summarize memory",
                    status="completed",
                    result_summary="Delegated summary",
                    tools_used=["read_files"],
                    duration_ms=24,
                    error_message=None,
                )
            ],
        }
    )

    assert any(
        isinstance(message, SystemMessage)
        and "Blocking Delegate Results" in message.content
        and "Delegated summary" in message.content
        for message in composed["input_messages"]
    )


def test_compose_inputs_does_not_reinject_consumed_delegate_results(tmp_path: Path):
    _seed_base(tmp_path)
    manager = AgentManager()
    manager.initialize(tmp_path)
    graph = manager._runtime_graph()
    result = ResolvedDelegateResult(
        delegate_id="del_1234",
        role="researcher",
        task="Summarize memory",
        status="completed",
        result_summary="Delegated summary",
        tools_used=["read_files"],
        duration_ms=24,
        error_message=None,
    )

    composed = graph._compose_inputs(
        {
            "base_system_prompt": "base prompt",
            "selected_skill_items": [],
            "messages": [],
            "model_messages": [],
            "compressed_context": "",
            "rag_context": None,
            "resolved_delegate_results": [result],
            "pending_delegate_result_injection": [],
        }
    )

    assert not any(
        isinstance(message, SystemMessage)
        and "Blocking Delegate Results" in message.content
        for message in composed["input_messages"]
    )


def test_compose_inputs_hides_stale_tool_turn_during_delegate_synthesis(tmp_path: Path):
    _seed_base(tmp_path)
    manager = AgentManager()
    manager.initialize(tmp_path)
    graph = manager._runtime_graph()

    delegate_call = AIMessage(
        content="I will delegate this task.",
        tool_calls=[
            {
                "name": "delegate",
                "args": {
                    "task": "Summarize memory",
                    "role": "researcher",
                    "wait_for_result": True,
                },
                "id": "call-1",
                "type": "tool_call",
            }
        ],
    )
    delegate_result = ResolvedDelegateResult(
        delegate_id="del_1234",
        role="researcher",
        task="Summarize memory",
        status="completed",
        result_summary="Delegated summary",
        tools_used=["read_files"],
        duration_ms=24,
        error_message=None,
    )

    composed = graph._compose_inputs(
        {
            "base_system_prompt": "base prompt",
            "selected_skill_items": [],
            "messages": [
                {
                    "role": "user",
                    "content": "delegate a researcher to summarize memory",
                }
            ],
            "model_messages": [
                delegate_call,
                ToolMessage(
                    content="delegate launched",
                    name="delegate",
                    tool_call_id="call-1",
                    status="success",
                ),
            ],
            "compressed_context": "",
            "rag_context": None,
            "resolved_delegate_results": [delegate_result],
            "pending_delegate_result_injection": [delegate_result],
        }
    )

    input_messages = composed["input_messages"]
    assert any(
        isinstance(message, HumanMessage)
        and message.content == "delegate a researcher to summarize memory"
        for message in input_messages
    )
    assert any(
        isinstance(message, SystemMessage)
        and "Blocking Delegate Results" in message.content
        and "Delegated summary" in message.content
        for message in input_messages
    )
    assert not any(
        isinstance(message, AIMessage) and message.tool_calls for message in input_messages
    )
    assert not any(isinstance(message, ToolMessage) for message in input_messages)


def test_runtime_discloses_partial_answer_after_blocking_delegate_failure(tmp_path: Path):
    _seed_base(tmp_path)
    manager = AgentManager()
    manager.initialize(tmp_path)
    graph = manager._runtime_graph()

    final_text = graph._ensure_delegate_failure_disclosure(
        "This is the final answer.",
        [
            ResolvedDelegateResult(
                delegate_id="del_1234",
                role="researcher",
                task="Summarize memory",
                status="failed",
                result_summary="",
                tools_used=[],
                duration_ms=42,
                error_message="delegate exploded",
            )
        ],
    )

    assert final_text.startswith("Partial answer:")
    assert "delegate exploded" in final_text


def test_model_step_clears_pending_delegate_injection_on_retry(
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    _seed_base(
        tmp_path,
        {
            "agent_runtime": {"max_retries": 1},
            "llm_defaults": {"default": "openai", "fallbacks": []},
        },
    )
    manager = AgentManager()
    manager.initialize(tmp_path)
    graph = manager._runtime_graph()
    runtime = manager.get_runtime("default")
    route = manager.runtime_services.resolve_llm_route(runtime)

    monkeypatch.setattr(
        manager.runtime_services,
        "get_runtime_llm",
        lambda runtime, profile: _StubToolCapableModel(profile.profile_name),
    )
    monkeypatch.setattr(
        manager.lcel_pipelines,
        "model_chain",
        lambda **kwargs: _RetryingChain([RuntimeError("temporary failure")]),
    )

    result = asyncio.run(
        graph._model_step(
            {
                "request": RuntimeRequest(
                    message="resume after delegate",
                    history=[],
                    session_id="session-retry-injection",
                    trigger_type="chat",
                    agent_id="default",
                ),
                "route": route,
                "candidate_index": 0,
                "retry_index": 0,
                "attempt_number": 0,
                "loop_count": 0,
                "run_id": "",
                "input_messages": [],
                "model_messages": [],
                "pending_new_response": False,
                "token_source": None,
                "fallback_final_text": "",
                "emitted_reasoning": set(),
                "usage_state": {},
                "usage_sources": {},
                "usage_signature": "",
                "pending_delegate_result_injection": [
                    ResolvedDelegateResult(
                        delegate_id="del_1234",
                        role="researcher",
                        task="Summarize memory",
                        status="completed",
                        result_summary="Delegated summary",
                        tools_used=["read_files"],
                        duration_ms=24,
                        error_message=None,
                    )
                ],
            }
        )
    )

    assert isinstance(result, Command)
    assert result.goto == "model_step"
    assert result.update["pending_delegate_result_injection"] == []


def test_model_step_clears_pending_delegate_injection_on_fallback(
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    _seed_base(
        tmp_path,
        {
            "agent_runtime": {"max_retries": 0},
            "llm_defaults": {"default": "openai", "fallbacks": ["deepseek"]},
        },
    )
    manager = AgentManager()
    manager.initialize(tmp_path)
    graph = manager._runtime_graph()
    runtime = manager.get_runtime("default")
    route = manager.runtime_services.resolve_llm_route(runtime)

    monkeypatch.setattr(
        manager.runtime_services,
        "get_runtime_llm",
        lambda runtime, profile: _StubToolCapableModel(profile.profile_name),
    )
    monkeypatch.setattr(
        manager.lcel_pipelines,
        "model_chain",
        lambda **kwargs: _RetryingChain([TimeoutError("delegate wait timed out")]),
    )

    result = asyncio.run(
        graph._model_step(
            {
                "request": RuntimeRequest(
                    message="resume after delegate",
                    history=[],
                    session_id="session-fallback-injection",
                    trigger_type="chat",
                    agent_id="default",
                ),
                "route": route,
                "candidate_index": 0,
                "retry_index": 0,
                "attempt_number": 0,
                "loop_count": 0,
                "run_id": "",
                "input_messages": [],
                "model_messages": [],
                "pending_new_response": False,
                "token_source": None,
                "fallback_final_text": "",
                "emitted_reasoning": set(),
                "usage_state": {},
                "usage_sources": {},
                "usage_signature": "",
                "pending_delegate_result_injection": [
                    ResolvedDelegateResult(
                        delegate_id="del_1234",
                        role="researcher",
                        task="Summarize memory",
                        status="completed",
                        result_summary="Delegated summary",
                        tools_used=["read_files"],
                        duration_ms=24,
                        error_message=None,
                    )
                ],
            }
        )
    )

    assert isinstance(result, Command)
    assert result.goto == "model_step"
    assert result.update["candidate_index"] == 1
    assert result.update["pending_delegate_result_injection"] == []
    assert result.update["pending_new_response"] is True


def test_model_step_clears_pending_delegate_injection_on_terminal_error(
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    _seed_base(
        tmp_path,
        {
            "agent_runtime": {"max_retries": 0},
            "llm_defaults": {"default": "openai", "fallbacks": []},
        },
    )
    manager = AgentManager()
    manager.initialize(tmp_path)
    graph = manager._runtime_graph()
    runtime = manager.get_runtime("default")
    route = manager.runtime_services.resolve_llm_route(runtime)

    monkeypatch.setattr(
        manager.runtime_services,
        "get_runtime_llm",
        lambda runtime, profile: _StubToolCapableModel(profile.profile_name),
    )
    monkeypatch.setattr(
        manager.lcel_pipelines,
        "model_chain",
        lambda **kwargs: _RetryingChain([RuntimeError("permanent failure")]),
    )

    result = asyncio.run(
        graph._model_step(
            {
                "request": RuntimeRequest(
                    message="resume after delegate",
                    history=[],
                    session_id="session-terminal-error-injection",
                    trigger_type="chat",
                    agent_id="default",
                ),
                "route": route,
                "candidate_index": 0,
                "retry_index": 0,
                "attempt_number": 0,
                "loop_count": 0,
                "run_id": "",
                "input_messages": [],
                "model_messages": [],
                "pending_new_response": False,
                "token_source": None,
                "fallback_final_text": "",
                "emitted_reasoning": set(),
                "usage_state": {},
                "usage_sources": {},
                "usage_signature": "",
                "pending_delegate_result_injection": [
                    ResolvedDelegateResult(
                        delegate_id="del_1234",
                        role="researcher",
                        task="Summarize memory",
                        status="completed",
                        result_summary="Delegated summary",
                        tools_used=["read_files"],
                        duration_ms=24,
                        error_message=None,
                    )
                ],
            }
        )
    )

    assert isinstance(result, Command)
    assert result.goto == "finalize_error"
    assert result.update["pending_delegate_result_injection"] == []
    assert result.update["error"].code == "stream_failed"


def test_model_step_exposes_no_tools_during_delegate_result_synthesis(
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    _seed_base(tmp_path)
    manager = AgentManager()
    manager.initialize(tmp_path)
    runtime = manager.get_runtime("default")
    runtime.runtime_config.delegation.enabled = True
    runtime.runtime_config.delegation.allowed_tool_scopes = {
        "researcher": ["read_files"],
    }
    manager.runtime_services.delegate_registry = DelegateRegistry(base_dir=tmp_path)
    graph = manager._runtime_graph()
    route = manager.runtime_services.resolve_llm_route(runtime)
    captured: dict[str, Any] = {}

    monkeypatch.setattr(
        manager.runtime_services,
        "get_runtime_llm",
        lambda runtime, profile: _StubToolCapableModel(profile.profile_name),
    )

    def _capture_model_chain(**kwargs):  # type: ignore[no-untyped-def]
        captured["tool_names"] = [tool.name for tool in kwargs.get("tools", [])]
        return _ScriptedChain([[AIMessageChunk(content="done")]])

    monkeypatch.setattr(manager.lcel_pipelines, "model_chain", _capture_model_chain)

    result = asyncio.run(
        graph._model_step(
            {
                "request": RuntimeRequest(
                    message="resume after delegate",
                    history=[],
                    session_id="session-hide-delegate-status",
                    trigger_type="chat",
                    agent_id="default",
                ),
                "route": route,
                "candidate_index": 0,
                "retry_index": 0,
                "attempt_number": 0,
                "loop_count": 0,
                "run_id": "",
                "input_messages": [],
                "model_messages": [],
                "pending_new_response": False,
                "token_source": None,
                "fallback_final_text": "",
                "emitted_reasoning": set(),
                "usage_state": {},
                "usage_sources": {},
                "usage_signature": "",
                "pending_delegate_result_injection": [
                    ResolvedDelegateResult(
                        delegate_id="del_1234",
                        role="researcher",
                        task="Summarize memory",
                        status="completed",
                        result_summary="Delegated summary",
                        tools_used=["read_files"],
                        duration_ms=24,
                        error_message=None,
                    )
                ],
            }
        )
    )

    assert captured["tool_names"] == []
    assert isinstance(result, Command)
    assert result.goto == "finalize_success"


def test_model_step_retries_once_when_delegate_synthesis_attempt_calls_tool(
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    _seed_base(tmp_path)
    manager = AgentManager()
    manager.initialize(tmp_path)
    graph = manager._runtime_graph()
    runtime = manager.get_runtime("default")
    route = manager.runtime_services.resolve_llm_route(runtime)
    captured: dict[str, Any] = {}

    monkeypatch.setattr(
        manager.runtime_services,
        "get_runtime_llm",
        lambda runtime, profile: _StubToolCapableModel(profile.profile_name),
    )

    def _capture_model_chain(**kwargs):  # type: ignore[no-untyped-def]
        captured["tool_names"] = [tool.name for tool in kwargs.get("tools", [])]
        return _ScriptedChain(
            [
                [
                    AIMessageChunk(
                        content="",
                        tool_call_chunks=[
                            {
                                "name": "read_files",
                                "args": '{"path":"memory/MEMORY.md"}',
                                "id": "call-1",
                                "index": 0,
                            }
                        ],
                    )
                ]
            ]
        )

    monkeypatch.setattr(manager.lcel_pipelines, "model_chain", _capture_model_chain)

    result = asyncio.run(
        graph._model_step(
            {
                "request": RuntimeRequest(
                    message="resume after delegate",
                    history=[],
                    session_id="session-synthesis-retry",
                    trigger_type="chat",
                    agent_id="default",
                ),
                "route": route,
                "candidate_index": 0,
                "retry_index": 0,
                "attempt_number": 0,
                "loop_count": 0,
                "run_id": "",
                "input_messages": [],
                "model_messages": [],
                "pending_new_response": False,
                "token_source": None,
                "fallback_final_text": "",
                "emitted_reasoning": set(),
                "usage_state": {},
                "usage_sources": {},
                "usage_signature": "",
                "pending_delegate_result_injection": [
                    ResolvedDelegateResult(
                        delegate_id="del_1234",
                        role="researcher",
                        task="Summarize memory",
                        status="completed",
                        result_summary="Delegated summary",
                        tools_used=["read_files"],
                        duration_ms=24,
                        error_message=None,
                    )
                ],
                "delegate_synthesis_retry_count": 0,
            }
        )
    )

    assert captured["tool_names"] == []
    assert isinstance(result, Command)
    assert result.goto == "model_step"
    assert result.update["delegate_synthesis_retry_count"] == 1
    assert len(result.update["pending_delegate_result_injection"]) == 1
    assert result.update["pending_tool_calls"] == []


def test_model_step_falls_back_after_second_delegate_synthesis_tool_call(
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    _seed_base(tmp_path)
    manager = AgentManager()
    manager.initialize(tmp_path)
    graph = manager._runtime_graph()
    runtime = manager.get_runtime("default")
    route = manager.runtime_services.resolve_llm_route(runtime)

    monkeypatch.setattr(
        manager.runtime_services,
        "get_runtime_llm",
        lambda runtime, profile: _StubToolCapableModel(profile.profile_name),
    )
    monkeypatch.setattr(
        manager.lcel_pipelines,
        "model_chain",
        lambda **kwargs: _ScriptedChain(
            [
                [
                    AIMessageChunk(
                        content="",
                        tool_call_chunks=[
                            {
                                "name": "read_files",
                                "args": '{"path":"memory/MEMORY.md"}',
                                "id": "call-1",
                                "index": 0,
                            }
                        ],
                    )
                ]
            ]
        ),
    )

    result = asyncio.run(
        graph._model_step(
            {
                "request": RuntimeRequest(
                    message="resume after delegate",
                    history=[],
                    session_id="session-synthesis-fallback",
                    trigger_type="chat",
                    agent_id="default",
                ),
                "route": route,
                "candidate_index": 0,
                "retry_index": 0,
                "attempt_number": 0,
                "loop_count": 0,
                "run_id": "",
                "input_messages": [],
                "model_messages": [],
                "pending_new_response": False,
                "token_source": None,
                "fallback_final_text": "",
                "emitted_reasoning": set(),
                "usage_state": {},
                "usage_sources": {},
                "usage_signature": "",
                "pending_delegate_result_injection": [
                    ResolvedDelegateResult(
                        delegate_id="del_1234",
                        role="researcher",
                        task="Summarize memory",
                        status="completed",
                        result_summary="Delegated summary",
                        tools_used=["read_files"],
                        duration_ms=24,
                        error_message=None,
                    )
                ],
                "delegate_synthesis_retry_count": 1,
            }
        )
    )

    assert isinstance(result, Command)
    assert result.goto == "finalize_success"
    assert result.update["delegate_synthesis_retry_count"] == 0
    assert result.update["pending_delegate_result_injection"] == []
    assert "synthesis step failed" in result.update["final_text"]
    assert "Delegated summary" in result.update["final_text"]


def test_model_step_retries_when_delegate_synthesis_emits_dsml_text_tool_intent(
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    _seed_base(tmp_path)
    manager = AgentManager()
    manager.initialize(tmp_path)
    graph = manager._runtime_graph()
    runtime = manager.get_runtime("default")
    route = manager.runtime_services.resolve_llm_route(runtime)

    monkeypatch.setattr(
        manager.runtime_services,
        "get_runtime_llm",
        lambda runtime, profile: _StubToolCapableModel(profile.profile_name),
    )
    emitted: list[str] = []
    monkeypatch.setattr(
        graph,
        "_emit",
        lambda event_type, data: emitted.append(event_type),
    )
    monkeypatch.setattr(
        manager.lcel_pipelines,
        "model_chain",
        lambda **kwargs: _ScriptedChain(
            [
                [
                    AIMessageChunk(
                        content=(
                            "\n<｜DSML｜function_calls>\n"
                            '<｜DSML｜invoke name="delegate_status">\n'
                            '<｜DSML｜parameter name="delegate_id" string="true">del_1234</｜DSML｜parameter>\n'
                            "</｜DSML｜invoke>\n"
                            "</｜DSML｜function_calls>"
                        )
                    )
                ]
            ]
        ),
    )

    result = asyncio.run(
        graph._model_step(
            {
                "request": RuntimeRequest(
                    message="resume after delegate",
                    history=[],
                    session_id="session-synthesis-dsml-retry",
                    trigger_type="chat",
                    agent_id="default",
                ),
                "route": route,
                "candidate_index": 0,
                "retry_index": 0,
                "attempt_number": 0,
                "loop_count": 0,
                "run_id": "",
                "input_messages": [],
                "model_messages": [],
                "pending_new_response": False,
                "token_source": None,
                "fallback_final_text": "",
                "emitted_reasoning": set(),
                "usage_state": {},
                "usage_sources": {},
                "usage_signature": "",
                "pending_delegate_result_injection": [
                    ResolvedDelegateResult(
                        delegate_id="del_1234",
                        role="researcher",
                        task="Summarize memory",
                        status="completed",
                        result_summary="Delegated summary",
                        tools_used=["read_files"],
                        duration_ms=24,
                        error_message=None,
                    )
                ],
                "delegate_synthesis_retry_count": 0,
            }
        )
    )

    assert isinstance(result, Command)
    assert result.goto == "model_step"
    assert result.update["delegate_synthesis_retry_count"] == 1
    assert len(result.update["pending_delegate_result_injection"]) == 1
    assert "token" not in emitted
    assert "new_response" not in emitted


def test_model_step_retries_when_delegate_synthesis_claims_delegate_still_running(
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    _seed_base(tmp_path)
    manager = AgentManager()
    manager.initialize(tmp_path)
    graph = manager._runtime_graph()
    runtime = manager.get_runtime("default")
    route = manager.runtime_services.resolve_llm_route(runtime)

    monkeypatch.setattr(
        manager.runtime_services,
        "get_runtime_llm",
        lambda runtime, profile: _StubToolCapableModel(profile.profile_name),
    )
    monkeypatch.setattr(
        manager.lcel_pipelines,
        "model_chain",
        lambda **kwargs: _ScriptedChain(
            [
                [
                    AIMessageChunk(
                        content=(
                            "已成功创建研究助手（delegate_id: del_1234）。研究助手正在独立运行中，"
                            "完成后我会将完整分析报告呈现给您。"
                        )
                    )
                ]
            ]
        ),
    )

    result = asyncio.run(
        graph._model_step(
            {
                "request": RuntimeRequest(
                    message="resume after delegate",
                    history=[],
                    session_id="session-synthesis-stale-running",
                    trigger_type="chat",
                    agent_id="default",
                ),
                "route": route,
                "candidate_index": 0,
                "retry_index": 0,
                "attempt_number": 0,
                "loop_count": 0,
                "run_id": "",
                "input_messages": [],
                "model_messages": [],
                "pending_new_response": False,
                "token_source": None,
                "fallback_final_text": "",
                "emitted_reasoning": set(),
                "usage_state": {},
                "usage_sources": {},
                "usage_signature": "",
                "pending_delegate_result_injection": [
                    ResolvedDelegateResult(
                        delegate_id="del_1234",
                        role="researcher",
                        task="Summarize memory",
                        status="completed",
                        result_summary="Delegated summary",
                        tools_used=["read_files"],
                        duration_ms=24,
                        error_message=None,
                    )
                ],
                "delegate_synthesis_retry_count": 0,
            }
        )
    )

    assert isinstance(result, Command)
    assert result.goto == "model_step"
    assert result.update["delegate_synthesis_retry_count"] == 1


def test_model_step_retries_when_delegate_synthesis_uses_started_waiting_language(
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    _seed_base(tmp_path)
    manager = AgentManager()
    manager.initialize(tmp_path)
    graph = manager._runtime_graph()
    runtime = manager.get_runtime("default")
    route = manager.runtime_services.resolve_llm_route(runtime)

    monkeypatch.setattr(
        manager.runtime_services,
        "get_runtime_llm",
        lambda runtime, profile: _StubToolCapableModel(profile.profile_name),
    )
    monkeypatch.setattr(
        manager.lcel_pipelines,
        "model_chain",
        lambda **kwargs: _ScriptedChain(
            [
                [
                    AIMessageChunk(
                        content=(
                            "研究员子代理已启动，正在分析memory/knowledge目录。"
                            "我会等待它完成分析并回报结果。"
                        )
                    )
                ]
            ]
        ),
    )

    result = asyncio.run(
        graph._model_step(
            {
                "request": RuntimeRequest(
                    message="resume after delegate",
                    history=[],
                    session_id="session-synthesis-started-waiting",
                    trigger_type="chat",
                    agent_id="default",
                ),
                "route": route,
                "candidate_index": 0,
                "retry_index": 0,
                "attempt_number": 0,
                "loop_count": 0,
                "run_id": "",
                "input_messages": [],
                "model_messages": [],
                "pending_new_response": False,
                "token_source": None,
                "fallback_final_text": "",
                "emitted_reasoning": set(),
                "usage_state": {},
                "usage_sources": {},
                "usage_signature": "",
                "pending_delegate_result_injection": [
                    ResolvedDelegateResult(
                        delegate_id="del_1234",
                        role="researcher",
                        task="Summarize memory",
                        status="completed",
                        result_summary="Delegated summary",
                        tools_used=["read_files"],
                        duration_ms=24,
                        error_message=None,
                    )
                ],
                "delegate_synthesis_retry_count": 0,
            }
        )
    )

    assert isinstance(result, Command)
    assert result.goto == "model_step"
    assert result.update["delegate_synthesis_retry_count"] == 1


def test_model_step_falls_back_after_second_dsml_text_tool_intent(
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    _seed_base(tmp_path)
    manager = AgentManager()
    manager.initialize(tmp_path)
    graph = manager._runtime_graph()
    runtime = manager.get_runtime("default")
    route = manager.runtime_services.resolve_llm_route(runtime)

    monkeypatch.setattr(
        manager.runtime_services,
        "get_runtime_llm",
        lambda runtime, profile: _StubToolCapableModel(profile.profile_name),
    )
    monkeypatch.setattr(
        manager.lcel_pipelines,
        "model_chain",
        lambda **kwargs: _ScriptedChain(
            [
                [
                    AIMessageChunk(
                        content=(
                            "\n<｜DSML｜function_calls>\n"
                            '<｜DSML｜invoke name="delegate_status">\n'
                            '<｜DSML｜parameter name="delegate_id" string="true">del_1234</｜DSML｜parameter>\n'
                            "</｜DSML｜invoke>\n"
                            "</｜DSML｜function_calls>"
                        )
                    )
                ]
            ]
        ),
    )

    result = asyncio.run(
        graph._model_step(
            {
                "request": RuntimeRequest(
                    message="resume after delegate",
                    history=[],
                    session_id="session-synthesis-dsml-fallback",
                    trigger_type="chat",
                    agent_id="default",
                ),
                "route": route,
                "candidate_index": 0,
                "retry_index": 0,
                "attempt_number": 0,
                "loop_count": 0,
                "run_id": "",
                "input_messages": [],
                "model_messages": [],
                "pending_new_response": False,
                "token_source": None,
                "fallback_final_text": "",
                "emitted_reasoning": set(),
                "usage_state": {},
                "usage_sources": {},
                "usage_signature": "",
                "pending_delegate_result_injection": [
                    ResolvedDelegateResult(
                        delegate_id="del_1234",
                        role="researcher",
                        task="Summarize memory",
                        status="completed",
                        result_summary="Delegated summary",
                        tools_used=["read_files"],
                        duration_ms=24,
                        error_message=None,
                    )
                ],
                "delegate_synthesis_retry_count": 1,
            }
        )
    )

    assert isinstance(result, Command)
    assert result.goto == "finalize_success"
    assert result.update["delegate_synthesis_retry_count"] == 0
    assert result.update["pending_delegate_result_injection"] == []
    assert "synthesis step failed" in result.update["final_text"]
    assert "Delegated summary" in result.update["final_text"]


def test_graph_runtime_streams_tool_loop_events(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    _seed_base(tmp_path)
    manager = AgentManager()
    manager.initialize(tmp_path)

    scripted = [
        [
            AIMessageChunk(
                content="",
                tool_call_chunks=[
                    {
                        "name": "read_files",
                        "args": '{"path":"memory/MEMORY.md"}',
                        "id": "call-1",
                        "index": 0,
                    }
                ],
            )
        ],
        [AIMessageChunk(content="final answer")],
    ]

    monkeypatch.setattr(
        manager.runtime_services,
        "get_runtime_llm",
        lambda runtime, profile: _StubToolCapableModel(profile.profile_name),
    )
    monkeypatch.setattr(
        manager.lcel_pipelines,
        "model_chain",
        lambda **kwargs: _ScriptedChain(scripted),
    )
    monkeypatch.setattr(
        manager.skill_selector,
        "select",
        lambda **kwargs: [
            SelectedSkill(
                name="read-helper",
                location="./skills/read-helper/SKILL.md",
                description="read files",
                reason="matched terms: read",
                score=10,
            )
        ],
    )

    async def collect():
        rows = []
        async for event in manager.astream(
            message="read the memory file",
            session_id="session-1",
            agent_id="default",
        ):
            rows.append(event)
        return rows

    events = asyncio.run(collect())
    event_types = [row["type"] for row in events]

    assert "selected_skills" in event_types
    assert "run_start" in event_types
    assert "tool_start" in event_types
    assert "tool_end" in event_types
    assert "new_response" in event_types
    assert "token" in event_types
    assert events[-1]["type"] == "done"
    assert events[-1]["data"]["content"] == "final answer"


def test_graph_runtime_rebuilds_model_input_after_tool_results(
    monkeypatch, tmp_path: Path
):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    _seed_base(tmp_path)
    manager = AgentManager()
    manager.initialize(tmp_path)

    payloads: list[dict[str, Any]] = []
    scripted = [
        [
            AIMessageChunk(
                content="",
                tool_call_chunks=[
                    {
                        "name": "read_files",
                        "args": '{"path":"memory/MEMORY.md"}',
                        "id": "call-1",
                        "index": 0,
                    }
                ],
            )
        ],
        [AIMessageChunk(content="final answer")],
    ]

    monkeypatch.setattr(
        manager.runtime_services,
        "get_runtime_llm",
        lambda runtime, profile: _StubToolCapableModel(profile.profile_name),
    )
    monkeypatch.setattr(
        manager.lcel_pipelines,
        "model_chain",
        lambda **kwargs: _RecordingScriptedChain(payloads, scripted),
    )

    async def collect():
        rows = []
        async for event in manager.astream(
            message="read the memory file",
            session_id="session-tool-loop",
            agent_id="default",
        ):
            rows.append(event)
        return rows

    events = asyncio.run(collect())

    assert events[-1]["type"] == "done"
    assert len(payloads) == 2
    second_messages = payloads[1]["messages"]
    assert any(getattr(message, "tool_calls", None) for message in second_messages)
    assert any(getattr(message, "tool_call_id", None) == "call-1" for message in second_messages)


def test_graph_runtime_enforces_max_steps(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    _seed_base(
        tmp_path,
        {
            "agent_runtime": {"max_steps": 1},
            "llm_defaults": {"default": "openai", "fallbacks": []},
        },
    )
    manager = AgentManager()
    manager.initialize(tmp_path)

    scripted = [
        [
            AIMessageChunk(
                content="",
                tool_call_chunks=[
                    {
                        "name": "read_files",
                        "args": '{"path":"memory/MEMORY.md"}',
                        "id": "call-1",
                        "index": 0,
                    }
                ],
            )
        ]
    ]

    monkeypatch.setattr(
        manager.runtime_services,
        "get_runtime_llm",
        lambda runtime, profile: _StubToolCapableModel(profile.profile_name),
    )
    monkeypatch.setattr(
        manager.lcel_pipelines,
        "model_chain",
        lambda **kwargs: _ScriptedChain(scripted),
    )

    async def collect():
        rows = []
        async for event in manager.astream(
            message="loop forever",
            session_id="session-2",
            agent_id="default",
        ):
            rows.append(event)
        return rows

    events = asyncio.run(collect())
    assert events[-1]["type"] == "error"
    assert events[-1]["data"]["code"] == "max_steps_reached"


def test_graph_runtime_emits_retrieval_and_usage(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    _seed_base(
        tmp_path,
        {
            "rag_mode": True,
            "llm_defaults": {"default": "openai", "fallbacks": []},
        },
    )
    manager = AgentManager()
    manager.initialize(tmp_path)

    monkeypatch.setattr(
        manager.get_runtime("default").memory_indexer,
        "retrieve",
        lambda *args, **kwargs: [{"score": 0.9, "text": "remembered fact"}],
    )
    monkeypatch.setattr(
        manager.runtime_services,
        "get_runtime_llm",
        lambda runtime, profile: _StubToolCapableModel(profile.profile_name),
    )
    monkeypatch.setattr(
        manager.lcel_pipelines,
        "model_chain",
        lambda **kwargs: _ScriptedChain([[AIMessageChunk(content="hello")]]),
    )

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

    monkeypatch.setattr(
        manager.runtime_services,
        "build_callbacks",
        lambda **kwargs: RuntimeCallbackBundle(
            callbacks=[],
            usage_capture=SimpleNamespace(snapshot=lambda: [usage_message]),
        ),
    )

    async def collect():
        rows = []
        async for event in manager.astream(
            message="use memory",
            session_id="session-3",
            agent_id="default",
        ):
            rows.append(event)
        return rows

    events = asyncio.run(collect())
    event_types = [row["type"] for row in events]

    assert "retrieval" in event_types
    assert "usage" in event_types
    assert events[-1]["type"] == "done"


def test_graph_runtime_retries_then_succeeds(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    _seed_base(
        tmp_path,
        {
            "agent_runtime": {"max_retries": 1},
            "llm_defaults": {"default": "openai", "fallbacks": []},
        },
    )
    manager = AgentManager()
    manager.initialize(tmp_path)

    monkeypatch.setattr(
        manager.runtime_services,
        "get_runtime_llm",
        lambda runtime, profile: _StubToolCapableModel(profile.profile_name),
    )
    outcomes: list[Exception | list[AIMessageChunk]] = [
        RuntimeError("temporary failure"),
        [AIMessageChunk(content="retry success")],
    ]
    monkeypatch.setattr(
        manager.lcel_pipelines,
        "model_chain",
        lambda **kwargs: _RetryingChain(outcomes),
    )

    async def collect():
        rows = []
        async for event in manager.astream(
            message="retry please",
            session_id="session-retry",
            agent_id="default",
        ):
            rows.append(event)
        return rows

    events = asyncio.run(collect())
    assert [row["type"] for row in events].count("run_start") == 2
    assert events[-1]["type"] == "done"
    assert events[-1]["data"]["content"] == "retry success"


def test_graph_runtime_injects_selected_skills_and_rag_context(
    monkeypatch, tmp_path: Path
):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    _seed_base(
        tmp_path,
        {
            "rag_mode": True,
            "llm_defaults": {"default": "openai", "fallbacks": []},
        },
    )
    manager = AgentManager()
    manager.initialize(tmp_path)

    monkeypatch.setattr(
        manager.get_runtime("default").memory_indexer,
        "retrieve",
        lambda *args, **kwargs: [{"score": 0.9, "text": "remembered fact"}],
    )
    monkeypatch.setattr(
        manager.skill_selector,
        "select",
        lambda **kwargs: [
            SelectedSkill(
                name="memory-helper",
                location="./skills/memory-helper/SKILL.md",
                description="memory helper",
                reason="matched terms: memory",
                score=10,
            )
        ],
    )
    monkeypatch.setattr(
        manager.runtime_services,
        "get_runtime_llm",
        lambda runtime, profile: _StubToolCapableModel(profile.profile_name),
    )

    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        manager.lcel_pipelines,
        "model_chain",
        lambda **kwargs: _CapturingChain(
            captured,
            [AIMessageChunk(content="grounded answer")],
        ),
    )

    async def collect():
        rows = []
        async for event in manager.astream(
            message="use memory",
            session_id="session-4",
            agent_id="default",
        ):
            rows.append(event)
        return rows

    events = asyncio.run(collect())
    payload = captured["payload"]
    assert "memory-helper" in payload["system_prompt"]
    assert any(
        isinstance(message, SystemMessage) and "remembered fact" in message.content
        for message in payload["messages"]
    )
    assert events[-1]["type"] == "done"
