from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableLambda

from graph.agent import AgentManager
from graph.lcel_pipelines import RuntimeLcelPipelines
from graph.runtime_execution_services import RuntimeCallbackBundle
from graph.skill_selector import SelectedSkill
from graph.tool_execution import ToolExecutionService
from tools.contracts import ToolResult


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
            "read the memory file",
            [],
            "session-1",
            is_first_turn=True,
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
            "read the memory file",
            [],
            "session-tool-loop",
            is_first_turn=True,
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
            "loop forever",
            [],
            "session-2",
            is_first_turn=True,
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
            "use memory",
            [],
            "session-3",
            is_first_turn=True,
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
            "retry please",
            [],
            "session-retry",
            is_first_turn=True,
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
            "use memory",
            [],
            "session-4",
            is_first_turn=True,
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
