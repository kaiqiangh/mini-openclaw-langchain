from __future__ import annotations

import operator
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any, Annotated, Literal, Protocol, TypedDict

from langchain_core.messages import BaseMessage
from langchain_core.runnables import Runnable, RunnableConfig

from graph.skill_selector import SelectedSkill
from llm_routing import ResolvedLlmRoute
from tools.contracts import ErrorCode


RuntimeEventType = Literal[
    "agent_update",
    "done",
    "error",
    "new_response",
    "reasoning",
    "retrieval",
    "run_start",
    "selected_skills",
    "token",
    "tool_end",
    "tool_start",
    "usage",
]


@dataclass(frozen=True)
class RuntimeRequest:
    message: str
    history: list[dict[str, Any]]
    session_id: str
    is_first_turn: bool = False
    output_format: str = "text"
    trigger_type: str = "chat"
    agent_id: str = "default"
    graph_name: str = "default"
    resume_same_turn: bool = False
    explicit_enabled_tools: list[str] | None = None
    explicit_blocked_tools: list[str] | None = None


@dataclass(frozen=True)
class RuntimeEvent:
    type: RuntimeEventType
    data: dict[str, Any]

    def as_payload(self) -> dict[str, Any]:
        return {"type": self.type, "data": self.data}


@dataclass(frozen=True)
class ToolExecutionEnvelope:
    tool: str
    tool_call_id: str
    args: dict[str, Any]
    output: str
    raw_output: str
    ok: bool
    duration_ms: int
    warnings: list[str] = field(default_factory=list)
    error_code: ErrorCode | None = None
    retryable: bool = False
    error_message: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RuntimeErrorInfo:
    error: str
    code: str
    run_id: str
    attempt: int

    def as_payload(self) -> dict[str, Any]:
        return {
            "error": self.error,
            "code": self.code,
            "run_id": self.run_id,
            "attempt": self.attempt,
        }


@dataclass(frozen=True)
class RuntimeResult:
    text: str = ""
    messages: list[BaseMessage] = field(default_factory=list)
    selected_skills: list[str] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    structured_response: Any | None = None
    token_source: str = "fallback"
    run_id: str = ""
    error: RuntimeErrorInfo | None = None


class RuntimeCheckpointer(Protocol):
    async def for_request(self, request: RuntimeRequest) -> Any | None:
        pass

    async def delete_thread(self, *, agent_id: str, thread_id: str) -> None:
        pass


class ToolCapableChatModel(Protocol):
    def bind_tools(
        self, tools: Sequence[Any], **kwargs: Any
    ) -> Runnable[Any, BaseMessage]:
        pass

    async def ainvoke(
        self, input: Any, config: RunnableConfig | None = None, **kwargs: Any
    ) -> Any:
        pass

    def astream(
        self, input: Any, config: RunnableConfig | None = None, **kwargs: Any
    ) -> AsyncIterator[Any]:
        pass


class GraphRuntime(Protocol):
    async def astream(self, request: RuntimeRequest):
        pass

    async def invoke(self, request: RuntimeRequest) -> RuntimeResult:
        pass

    async def aget_state(self, request: RuntimeRequest) -> dict[str, Any]:
        pass

    async def aget_state_history(
        self, request: RuntimeRequest
    ) -> list[dict[str, Any]]:
        pass

    async def aupdate_state(
        self, request: RuntimeRequest, values: dict[str, Any]
    ) -> dict[str, Any]:
        pass


class RuntimeGraphState(TypedDict, total=False):
    request: RuntimeRequest
    route: ResolvedLlmRoute
    base_system_prompt: str
    system_prompt: str
    rag_mode: bool
    compressed_context: str
    retrieval_results: list[dict[str, Any]]
    rag_context: str | None
    messages: list[dict[str, Any]]
    live_response: dict[str, Any] | None
    assistant_segments: list[dict[str, Any]]
    selected_skill_names: list[str]
    selected_skill_items: list[SelectedSkill]
    candidate_index: int
    retry_index: int
    attempt_number: int
    loop_count: int
    run_id: str
    active_model: str
    input_messages: list[BaseMessage]
    model_messages: list[BaseMessage]
    pending_tool_calls: list[dict[str, Any]]
    pending_new_response: bool
    token_source: str | None
    latest_model_snapshot: str
    fallback_final_text: str
    final_text: str
    emitted_reasoning: set[str]
    usage_state: dict[str, Any]
    usage_sources: dict[str, dict[str, int]]
    usage_signature: str
    usage_payload: dict[str, Any]
    structured_response: Any | None
    runtime_events: Annotated[list[RuntimeEvent], operator.add]
    tool_history: Annotated[list[ToolExecutionEnvelope], operator.add]
    error: RuntimeErrorInfo | None
