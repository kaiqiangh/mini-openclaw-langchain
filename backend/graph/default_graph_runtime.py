from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from langchain_core.messages import AIMessage, BaseMessage, message_chunk_to_message
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from graph.compaction import CompactionPipeline, CompactionSummary
from graph.lcel_pipelines import RuntimeLcelPipelines
from graph.retrieval_orchestrator import RetrievalOrchestrator
from graph.runtime_types import (
    GraphRuntime,
    RuntimeCheckpointer,
    RuntimeErrorInfo,
    RuntimeEvent,
    RuntimeGraphState,
    RuntimeRequest,
    RuntimeResult,
)
from graph.skill_selector import SkillSelector
from graph.stream_orchestrator import StreamOrchestrator
from graph.tool_execution import ToolExecutionService
from llm_routing import (
    classify_llm_failure,
    inspect_profile_availability,
    should_fallback_for_error,
)
from tools.base import ToolContext
from tools.delegate_tool import build_delegate_tool, build_delegate_status_tool
from usage.pricing import calculate_cost_breakdown, infer_provider
from hooks.engine import HookEngine
from hooks.types import HookEvent


class DefaultGraphRuntime(GraphRuntime):
    def __init__(
        self,
        *,
        services: Any,
        pipelines: RuntimeLcelPipelines,
        skill_selector: SkillSelector,
        checkpointer: RuntimeCheckpointer | None = None,
        hook_engine: HookEngine | None = None,
    ) -> None:
        self.services = services
        self.pipelines = pipelines
        self.skill_selector = skill_selector
        self.checkpointer = checkpointer
        self.hook_engine = hook_engine
        self._graphs: dict[object | None, Any] = {None: self._compile_graph(None)}

    def _resolve_hook_engine(self, agent_id: str) -> "HookEngine | None":
        """Resolve HookEngine per-agent: prefer per-agent engine from services, fall back to default."""
        engine = self.services.get_hook_engine(agent_id)
        if engine is not None:
            return engine
        return self.hook_engine

    def _hook_enabled(self, agent_id: str) -> bool:
        """Check if hooks are enabled for a given agent."""
        engine = self._resolve_hook_engine(agent_id)
        return engine is not None and engine.is_enabled

    @staticmethod
    def _hook_timestamp() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _append_hook_audit_event(
        self,
        *,
        trigger_type: str,
        hook_event: HookEvent,
        status: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        runtime = self.services.get_runtime(hook_event.agent_id)
        runtime.audit_store.append_step(
            run_id=hook_event.run_id or "",
            session_id=hook_event.session_id or "",
            trigger_type=trigger_type,
            event=f"hook_{hook_event.hook_type}",
            details={
                "agent_id": hook_event.agent_id,
                "hook_type": hook_event.hook_type,
                "status": status,
                "session_id": hook_event.session_id or "",
                "run_id": hook_event.run_id or "",
                "timestamp": hook_event.timestamp,
                **(details or {}),
            },
        )

    async def invoke(self, request: RuntimeRequest) -> RuntimeResult:
        session_repository = self.services.require_session_repository()
        prepared_request = await session_repository.prepare_runtime_request(request)
        graph = await self._graph_for_request(prepared_request)
        final_state = await graph.ainvoke(
            self._initial_state(prepared_request),
            config=self._graph_config(prepared_request),
        )
        if not isinstance(final_state, dict):
            raise RuntimeError("Graph returned an invalid final state")
        error = final_state.get("error")
        result = RuntimeResult(
            text=str(final_state.get("final_text", "")),
            messages=list(final_state.get("model_messages", [])),
            selected_skills=[
                item.name for item in final_state.get("selected_skill_items", [])
            ],
            usage=dict(final_state.get("usage_payload", {})),
            structured_response=final_state.get("structured_response"),
            token_source=str(final_state.get("token_source", "fallback") or "fallback"),
            run_id=str(final_state.get("run_id", "")),
            error=error if isinstance(error, RuntimeErrorInfo) else None,
        )
        if result.error is None:
            await session_repository.persist_invoke_result(prepared_request, result)
        else:
            await session_repository.fail_stream(prepared_request)
        return result

    async def astream(self, request: RuntimeRequest):
        session_repository = self.services.require_session_repository()
        prepared_request = await session_repository.prepare_runtime_request(request)
        graph = await self._graph_for_request(prepared_request)
        try:
            async for mode, chunk in graph.astream(
                self._initial_state(prepared_request),
                config=self._graph_config(prepared_request),
                stream_mode=["custom"],
            ):
                if mode != "custom" or not isinstance(chunk, RuntimeEvent):
                    continue
                await session_repository.apply_stream_event(prepared_request, chunk)
                yield chunk
        except Exception:
            await session_repository.fail_stream(prepared_request)
            raise
        else:
            await session_repository.finalize_stream(prepared_request)

    async def aget_state(self, request: RuntimeRequest) -> dict[str, Any]:
        graph = await self._graph_for_request(request)
        snapshot = await graph.aget_state(self._graph_config(request))
        if not isinstance(getattr(snapshot, "values", None), dict):
            return {}
        return dict(snapshot.values)

    async def aget_state_history(self, request: RuntimeRequest) -> list[dict[str, Any]]:
        graph = await self._graph_for_request(request)
        rows: list[dict[str, Any]] = []
        async for snapshot in graph.aget_state_history(self._graph_config(request)):
            values = getattr(snapshot, "values", None)
            if isinstance(values, dict):
                rows.append(dict(values))
        return rows

    async def aupdate_state(
        self, request: RuntimeRequest, values: dict[str, Any]
    ) -> dict[str, Any]:
        graph = await self._graph_for_request(request)
        await graph.aupdate_state(
            self._graph_config(request),
            values,
            as_node="prepare_request",
        )
        return await self.aget_state(request)

    async def _graph_for_request(self, request: RuntimeRequest):
        if self.checkpointer is None:
            return self._graphs[None]
        configured = await self.checkpointer.for_request(request)
        if configured is None:
            return self._graphs[None]
        key = id(configured)
        cached = self._graphs.get(key)
        if cached is not None:
            return cached
        compiled = self._compile_graph(checkpointer=configured)
        self._graphs[key] = compiled
        return compiled

    def _graph_config(self, request: RuntimeRequest) -> dict[str, Any]:
        runtime = self.services.get_runtime(request.agent_id).runtime_config
        max_steps = max(1, int(runtime.agent_runtime.max_steps))
        return {
            "recursion_limit": max(64, max_steps * 6 + 20),
            "configurable": {"thread_id": request.session_id},
        }

    @staticmethod
    def _initial_state(request: RuntimeRequest) -> RuntimeGraphState:
        return {
            "request": request,
            "candidate_index": 0,
            "retry_index": 0,
            "attempt_number": 0,
            "loop_count": 0,
            "run_id": "",
            "input_messages": [],
            "model_messages": [],
            "pending_tool_calls": [],
            "pending_new_response": False,
            "token_source": None,
            "latest_model_snapshot": "",
            "fallback_final_text": "",
            "final_text": "",
            "emitted_reasoning": set(),
            "usage_state": {},
            "usage_sources": {},
            "usage_signature": "",
            "usage_payload": {},
            "runtime_events": [],
            "tool_history": [],
            "structured_response": None,
            "error": None,
        }

    def _compile_graph(self, checkpointer: Any | None):
        builder = StateGraph(RuntimeGraphState)
        builder.add_node("prepare_request", self._prepare_request)
        builder.add_node("retrieve_context", self._retrieve_context)
        builder.add_node("select_skills", self._select_skills)
        builder.add_node("compose_inputs", self._compose_inputs)
        builder.add_node("model_step", self._model_step)
        builder.add_node("tool_step", self._tool_step)
        builder.add_node("finalize_success", self._finalize_success)
        builder.add_node("finalize_error", self._finalize_error)
        builder.add_node("__compact__", self._compact_step)
        builder.add_edge(START, "prepare_request")
        builder.add_edge("retrieve_context", "select_skills")
        builder.add_edge("select_skills", "compose_inputs")
        builder.add_edge("compose_inputs", "model_step")
        builder.add_edge("tool_step", "compose_inputs")
        builder.add_edge("__compact__", "compose_inputs")
        builder.add_edge("finalize_success", END)
        builder.add_edge("finalize_error", END)
        return builder.compile(checkpointer=checkpointer)

    @staticmethod
    def _emit(event_type: str, data: dict[str, Any]) -> None:
        try:
            writer = get_stream_writer()
            writer(RuntimeEvent(type=event_type, data=data))
        except Exception:
            return

    @staticmethod
    def _as_text(content: Any) -> str:
        return StreamOrchestrator.as_text(content)

    @staticmethod
    def _extract_token_text(token: Any) -> list[str]:
        return StreamOrchestrator.extract_token_text(token)

    @staticmethod
    def _extract_reasoning_text(message: Any) -> list[str]:
        return StreamOrchestrator.extract_reasoning_text(message)

    @staticmethod
    def _coerce_ai_message(message: BaseMessage) -> AIMessage:
        if isinstance(message, AIMessage):
            return message
        return AIMessage(content=str(getattr(message, "content", "")))

    @staticmethod
    def _is_max_steps_error(exc: Exception) -> bool:
        text = str(exc).strip().lower()
        if not text:
            return False
        return (
            "recursion limit" in text
            or "max steps" in text
            or "max_steps" in text
        )

    def _emit_usage_event(
        self,
        *,
        state: RuntimeGraphState,
        request: RuntimeRequest,
        run_id: str,
    ) -> None:
        usage_state = state.get("usage_state", {})
        cost = calculate_cost_breakdown(
            provider=str(usage_state.get("provider", "unknown")),
            model=str(usage_state.get("model", "unknown")),
            input_tokens=self.services.as_int(usage_state.get("input_tokens", 0)),
            input_uncached_tokens=self.services.as_int(
                usage_state.get("input_uncached_tokens", 0)
            ),
            input_cache_read_tokens=self.services.as_int(
                usage_state.get("input_cache_read_tokens", 0)
            ),
            input_cache_write_tokens_5m=self.services.as_int(
                usage_state.get("input_cache_write_tokens_5m", 0)
            ),
            input_cache_write_tokens_1h=self.services.as_int(
                usage_state.get("input_cache_write_tokens_1h", 0)
            ),
            input_cache_write_tokens_unknown=self.services.as_int(
                usage_state.get("input_cache_write_tokens_unknown", 0)
            ),
            output_tokens=self.services.as_int(usage_state.get("output_tokens", 0)),
        )
        self._emit(
            "usage",
            {
                "run_id": run_id,
                "agent_id": request.agent_id,
                "provider": usage_state.get("provider", "unknown"),
                "model": usage_state.get("model", "unknown"),
                **usage_state,
                "pricing": cost,
                "priced": bool(cost.get("priced", False)),
                "cost_usd": cost.get("total_cost_usd"),
            },
        )

    def _prepare_request(
        self, state: RuntimeGraphState
    ) -> Command[Literal["retrieve_context", "finalize_error"]]:
        request = state["request"]
        runtime_state = self.services.get_runtime(request.agent_id)
        effective_runtime = runtime_state.runtime_config
        route = self.services.resolve_llm_route(runtime_state)
        if not route.valid:
            run_id = str(uuid.uuid4())
            return Command(
                update={
                    "route": route,
                    "run_id": run_id,
                    "error": RuntimeErrorInfo(
                        error=self.services.route_error_message(route),
                        code="stream_failed",
                        run_id=run_id,
                        attempt=0,
                    ),
                },
                goto="finalize_error",
            )

        run_id = str(uuid.uuid4())
        run_id_candidate = run_id
        hook_engine = self._resolve_hook_engine(request.agent_id)
        if hook_engine and hook_engine.is_enabled:
            hook_event = HookEvent(
                hook_type="pre_run",
                agent_id=request.agent_id,
                session_id=request.session_id,
                run_id=str(run_id_candidate),
                timestamp=self._hook_timestamp(),
                payload={"message_length": len(str(request.message))},
            )
            hook_result = hook_engine.dispatch_sync(hook_event)
            self._append_hook_audit_event(
                trigger_type=request.trigger_type,
                hook_event=hook_event,
                status="allow" if hook_result.allow else "deny",
                details={
                    "message_length": len(str(request.message)),
                    "reason": hook_result.reason,
                },
            )
            if not hook_result.allow:
                return Command(
                    update={
                        "route": route,
                        "run_id": run_id,
                        "error": RuntimeErrorInfo(
                            error=f"Hook denied pre_run: {hook_result.reason}",
                            code="hook_denied",
                            run_id=run_id,
                            attempt=0,
                        ),
                    },
                    goto="finalize_error",
                )

        seed_candidate = route.candidates[0] if route.candidates else None
        provider = "unknown"
        model = "unknown"
        if seed_candidate is not None:
            model = seed_candidate.profile.model
            provider = infer_provider(
                model,
                base_url=seed_candidate.profile.base_url,
                explicit_provider=seed_candidate.profile.provider_id,
            )

        return Command(
            update={
                "route": route,
                "base_system_prompt": self.services.build_system_prompt(
                    rag_mode=effective_runtime.rag_mode,
                    is_first_turn=request.is_first_turn,
                    agent_id=request.agent_id,
                ),
                "system_prompt": "",
                "rag_mode": effective_runtime.rag_mode,
                "retrieval_results": [],
                "rag_context": None,
                "selected_skill_items": [],
                "usage_state": self.services.initial_usage_state(
                    provider=provider,
                    model=model,
                ),
                "usage_sources": {},
                "usage_signature": "",
            },
            goto="retrieve_context",
        )

    def _retrieve_context(self, state: RuntimeGraphState) -> dict[str, Any]:
        request = state["request"]
        runtime_state = self.services.get_runtime(request.agent_id)
        retrieval_envelope = RetrievalOrchestrator.build_envelope(
            runtime=runtime_state.runtime_config,
            memory_indexer=runtime_state.memory_indexer,
            message=request.message,
        )
        if retrieval_envelope.rag_mode:
            self._emit(
                "retrieval",
                {
                    "query": request.message,
                    "results": retrieval_envelope.results,
                },
            )
        return {
            "retrieval_results": retrieval_envelope.results,
            "rag_context": retrieval_envelope.rag_context,
        }

    def _select_skills(self, state: RuntimeGraphState) -> dict[str, Any]:
        request = state["request"]
        runtime_state = self.services.get_runtime(request.agent_id)
        selected = self.skill_selector.select(
            base_dir=runtime_state.root_dir,
            message=request.message,
            history=request.history,
        )
        if selected:
            self._emit(
                "selected_skills",
                {
                    "skills": [
                        {
                            "name": item.name,
                            "location": item.location,
                            "reason": item.reason,
                        }
                        for item in selected
                    ]
                },
            )
        return {"selected_skill_items": selected}

    def _compose_inputs(self, state: RuntimeGraphState) -> dict[str, Any]:
        system_prompt = self.pipelines.system_prompt_chain().invoke(
            {
                "base_system_prompt": state.get("base_system_prompt", ""),
                "selected_skills": state.get("selected_skill_items", []),
            }
        )
        messages = self.pipelines.message_chain().invoke(
            {
                "history": state.get("messages", []),
                "turn_messages": state.get("model_messages", []),
                "message": "",
                "compressed_context": state.get("compressed_context", ""),
                "rag_context": state.get("rag_context"),
            }
        )
        return {"system_prompt": system_prompt, "input_messages": messages}

    async def _model_step(
        self, state: RuntimeGraphState
    ) -> Command[
        Literal["model_step", "tool_step", "finalize_success", "finalize_error"]
    ]:
        request = state["request"]
        runtime_state = self.services.get_runtime(request.agent_id)
        effective_runtime = runtime_state.runtime_config
        route = state["route"]
        candidate_index = int(state.get("candidate_index", 0))

        if candidate_index >= len(route.candidates):
            run_id = str(uuid.uuid4())
            return Command(
                update={
                    "run_id": run_id,
                    "error": RuntimeErrorInfo(
                        error=f"Agent '{request.agent_id}' has no available LLM candidates",
                        code="stream_failed",
                        run_id=run_id,
                        attempt=int(state.get("attempt_number", 0)),
                    ),
                },
                goto="finalize_error",
            )

        candidate = route.candidates[candidate_index]
        availability = inspect_profile_availability(candidate.profile)
        if not availability.available:
            skipped_run_id = str(uuid.uuid4())
            self.services.append_llm_route_event(
                runtime=runtime_state,
                run_id=skipped_run_id,
                session_id=request.session_id,
                trigger_type=request.trigger_type,
                event="llm_route_skipped",
                details={
                    "profile": candidate.profile_name,
                    "source": candidate.source,
                    "reasons": list(availability.reasons),
                },
            )
            if candidate.source == "default":
                return Command(
                    update={
                        "run_id": skipped_run_id,
                        "error": RuntimeErrorInfo(
                            error=self.services.candidate_unavailable_message(
                                runtime_state.agent_id,
                                candidate,
                                availability.reasons,
                            ),
                            code="stream_failed",
                            run_id=skipped_run_id,
                            attempt=int(state.get("attempt_number", 0)),
                        ),
                    },
                    goto="finalize_error",
                )
            return Command(
                update={
                    "candidate_index": candidate_index + 1,
                    "retry_index": 0,
                    "run_id": "",
                    "loop_count": 0,
                },
                goto="model_step",
            )

        run_id = str(state.get("run_id", "")).strip()
        attempt_number = int(state.get("attempt_number", 0))
        retry_index = int(state.get("retry_index", 0))
        loop_count = int(state.get("loop_count", 0)) + 1

        if not run_id:
            run_id = str(uuid.uuid4())
            attempt_number += 1
            self.services.append_llm_route_event(
                runtime=runtime_state,
                run_id=run_id,
                session_id=request.session_id,
                trigger_type=request.trigger_type,
                event="llm_route_resolved",
                details={
                    "profile": candidate.profile_name,
                    "source": candidate.source,
                    "candidate_index": candidate_index,
                    "attempt": attempt_number,
                },
            )
            if candidate.source == "fallback":
                self.services.append_llm_route_event(
                    runtime=runtime_state,
                    run_id=run_id,
                    session_id=request.session_id,
                    trigger_type=request.trigger_type,
                    event="llm_fallback_selected",
                    details={
                        "profile": candidate.profile_name,
                        "candidate_index": candidate_index,
                        "attempt": attempt_number,
                    },
                )
            self._emit("run_start", {"run_id": run_id, "attempt": attempt_number})

        max_steps = max(1, int(effective_runtime.agent_runtime.max_steps))
        if loop_count > max_steps:
            error_text = (
                f"Recursion limit of {max_steps} reached without hitting a stop condition."
            )
            self.services.append_llm_route_event(
                runtime=runtime_state,
                run_id=run_id,
                session_id=request.session_id,
                trigger_type=request.trigger_type,
                event="llm_route_exhausted",
                details={
                    "profile": candidate.profile_name,
                    "failure_kind": "other",
                    "error": error_text,
                },
            )
            return Command(
                update={
                    "run_id": run_id,
                    "attempt_number": attempt_number,
                    "loop_count": loop_count,
                    "error": RuntimeErrorInfo(
                        error=error_text,
                        code="max_steps_reached",
                        run_id=run_id,
                        attempt=attempt_number,
                    ),
                },
                goto="finalize_error",
            )

        delegate_tools = []
        drv = getattr(self.services, "delegate_registry", None)
        am = getattr(self.services, "_agent_manager", None)
        delegation_config = effective_runtime.delegation
        request_explicit_enabled = request.explicit_enabled_tools
        request_explicit_blocked = request.explicit_blocked_tools
        if (
            drv
            and request_explicit_enabled is None
            and request_explicit_blocked is None
        ):
            ctx = ToolContext(
                workspace_root=runtime_state.root_dir,
                trigger_type=request.trigger_type,
                agent_id=request.agent_id,
                explicit_enabled_tools=(),
                explicit_blocked_tools=(),
                run_id=run_id,
                session_id=request.session_id,
            )
            delegate_tools.append(build_delegate_status_tool(registry=drv, context=ctx))
            if am and delegation_config.enabled:
                delegate_tools.append(build_delegate_tool(
                    agent_manager=am,
                    registry=drv,
                    base_dir=self.services.require_base_dir(),
                    context=ctx,
                ))
        hook_engine = self._resolve_hook_engine(request.agent_id)
        tool_service = ToolExecutionService.build(
            config_base_dir=self.services.require_base_dir(),
            runtime_root=runtime_state.root_dir,
            runtime=effective_runtime,
            trigger_type=request.trigger_type,
            agent_id=request.agent_id,
            run_id=run_id,
            session_id=request.session_id,
            runtime_audit_store=runtime_state.audit_store,
            delegate_tools=delegate_tools if delegate_tools else None,
            hook_engine=hook_engine,
            explicit_enabled_tools=request_explicit_enabled,
            explicit_blocked_tools=request_explicit_blocked,
        )
        usage_state = dict(state.get("usage_state", {}))
        usage_sources = dict(state.get("usage_sources", {}))
        prior_signature = str(state.get("usage_signature", ""))
        callback_bundle = self.services.build_callbacks(
            run_id=run_id,
            session_id=request.session_id,
            trigger_type=request.trigger_type,
            runtime_root=runtime_state.root_dir,
            runtime_audit_store=runtime_state.audit_store,
        )
        active_llm, active_model = self.services.resolve_tool_capable_model(
            runtime=runtime_state,
            candidate=candidate,
            has_tools=bool(tool_service.tools),
            tool_loop_model=route.tool_loop_model,
            tool_loop_model_overrides=route.tool_loop_model_overrides,
        )

        chain = self.pipelines.model_chain(llm=active_llm, tools=tool_service.tools)

        # PrePromptSubmit hook
        hook_engine = self._resolve_hook_engine(state["request"].agent_id)
        hook_result = None
        if hook_engine and hook_engine.is_enabled:
            hook_event = HookEvent(
                hook_type="pre_prompt_submit",
                agent_id=state["request"].agent_id,
                session_id=state["request"].session_id,
                run_id=state.get("run_id", ""),
                timestamp=self._hook_timestamp(),
                payload={
                    "message_count": len(state.get("input_messages", [])),
                },
            )
            hook_result = hook_engine.dispatch_sync(hook_event)
            self._append_hook_audit_event(
                trigger_type=state["request"].trigger_type,
                hook_event=hook_event,
                status="allow" if hook_result.allow else "deny",
                details={
                    "message_count": len(state.get("input_messages", [])),
                    "reason": hook_result.reason,
                },
            )
            if not hook_result.allow:
                self._emit("hook_denied", {"hook_type": "pre_prompt_submit", "reason": hook_result.reason})
                return Command(
                    goto="finalize_error",
                    update={
                        "error": RuntimeErrorInfo(
                            error=f"Hook denied pre_prompt_submit: {hook_result.reason}",
                            code="hook_denied",
                            run_id=state.get("run_id", ""),
                        ),
                    },
                )

        emitted_agent_update = False

        # Apply prompt modifications from hook (only if hook was active)
        if hook_result is not None and hook_result.modifications.get(
            "system_prompt_prefix"
        ):
            prefix = hook_result.modifications["system_prompt_prefix"]
            input_messages = list(state.get("input_messages", []))
            if input_messages:
                first_msg = input_messages[0]
                if hasattr(first_msg, "content"):
                    first_msg = type(first_msg)(content=prefix + str(first_msg.content))
                    input_messages[0] = first_msg
                state = {**state, "input_messages": input_messages}

        pending_new_response = bool(state.get("pending_new_response", False))
        token_source = str(state.get("token_source") or "").strip() or None
        fallback_final_text = str(state.get("fallback_final_text", ""))
        emitted_reasoning = set(state.get("emitted_reasoning", set()))
        model_messages = list(state.get("model_messages", []))
        streamed_parts: list[str] = []
        merged_chunk: Any | None = None

        try:
            async for chunk in chain.astream(
                {
                    "system_prompt": state.get("system_prompt", ""),
                    "messages": state.get("input_messages", []),
                },
                config={
                    "callbacks": callback_bundle.callbacks,
                    "configurable": {"thread_id": request.session_id},
                },
            ):
                merged_chunk = chunk if merged_chunk is None else merged_chunk + chunk

                chunk_texts = self._extract_token_text(chunk)
                if chunk_texts and not emitted_agent_update:
                    self._emit(
                        "agent_update",
                        {
                            "run_id": run_id,
                            "node": "model",
                            "message_count": 1,
                            "preview": "Streaming token output",
                        },
                    )
                    emitted_agent_update = True

                for text in chunk_texts:
                    if not text:
                        continue
                    if pending_new_response:
                        self._emit("new_response", {})
                        pending_new_response = False
                    streamed_parts.append(text)
                    token_source = "messages"
                    self._emit(
                        "token",
                        {
                            "content": text,
                            "source": "messages",
                        },
                    )

                for reasoning in self._extract_reasoning_text(chunk):
                    normalized = reasoning.strip()
                    if not normalized or normalized in emitted_reasoning:
                        continue
                    emitted_reasoning.add(normalized)
                    self._emit(
                        "reasoning",
                        {
                            "run_id": run_id,
                            "content": normalized[:1000],
                        },
                    )

            final_message = self._coerce_ai_message(
                message_chunk_to_message(merged_chunk)
                if merged_chunk is not None
                else AIMessage(content="")
            )
            final_content = self._as_text(final_message.content)

            if final_content:
                fallback_final_text = final_content
                if not streamed_parts:
                    if not emitted_agent_update:
                        self._emit(
                            "agent_update",
                            {
                                "run_id": run_id,
                                "node": "model",
                                "message_count": 1,
                                "preview": final_content[:500],
                            },
                        )
                        emitted_agent_update = True
                    if pending_new_response:
                        self._emit("new_response", {})
                        pending_new_response = False
                    streamed_parts.append(final_content)
                    token_source = "updates"
                    self._emit(
                        "token",
                        {
                            "content": final_content,
                            "source": "updates",
                        },
                    )

            if not emitted_agent_update:
                preview = final_content[:500]
                if not preview and final_message.tool_calls:
                    preview = f"Tool calls: {len(final_message.tool_calls)}"
                if not preview:
                    preview = "Model response"
                self._emit(
                    "agent_update",
                    {
                        "run_id": run_id,
                        "node": "model",
                        "message_count": 1,
                        "preview": preview,
                    },
                )

            captured_messages = callback_bundle.usage_capture.snapshot()
            self.services.accumulate_usage_from_messages(
                usage_state=usage_state,
                usage_sources=usage_sources,
                messages=captured_messages,
                source_prefix=f"llm_end:{run_id}",
                fallback_model=active_model,
                fallback_base_url=candidate.profile.base_url,
                fallback_provider=candidate.profile.provider_id,
            )
            if self.services.as_int(usage_state.get("total_tokens", 0)) <= 0:
                self.services.accumulate_usage_from_messages(
                    usage_state=usage_state,
                    usage_sources=usage_sources,
                    messages=[final_message],
                    source_prefix=f"result:{run_id}",
                    fallback_model=active_model,
                    fallback_base_url=candidate.profile.base_url,
                    fallback_provider=candidate.profile.provider_id,
                )

            next_signature = self.services.usage_signature(usage_state)
            if (
                next_signature != prior_signature
                and self.services.as_int(usage_state.get("total_tokens", 0)) > 0
            ):
                self._emit_usage_event(
                    state={"usage_state": usage_state},
                    request=request,
                    run_id=run_id,
                )

            tool_calls = list(final_message.tool_calls or [])
            if tool_calls:
                for call in tool_calls:
                    self._emit(
                        "tool_start",
                        {
                            "run_id": run_id,
                            "tool": str(call.get("name", "unknown")),
                            "input": call.get("args", {}),
                        },
                    )
                return Command(
                    update={
                        "run_id": run_id,
                        "active_model": active_model,
                        "attempt_number": attempt_number,
                        "loop_count": loop_count,
                        "retry_index": retry_index,
                        "model_messages": [*model_messages, final_message],
                        "pending_tool_calls": tool_calls,
                        "pending_new_response": pending_new_response,
                        "token_source": token_source,
                        "fallback_final_text": fallback_final_text,
                        "usage_state": usage_state,
                        "usage_sources": usage_sources,
                        "usage_signature": next_signature,
                        "emitted_reasoning": emitted_reasoning,
                    },
                    goto="tool_step",
                )

            final_text = "".join(streamed_parts).strip() or fallback_final_text
            usage_payload: dict[str, Any] = {}
            if self.services.as_int(usage_state.get("total_tokens", 0)) > 0:
                usage_payload = self.services.record_usage(
                    usage=usage_state,
                    run_id=run_id,
                    session_id=request.session_id,
                    trigger_type=request.trigger_type,
                    agent_id=request.agent_id,
                    usage_store=runtime_state.usage_store,
                )

            # Check token budget before finalizing — route to compaction if needed
            messages_for_budget = list(state.get("input_messages", [])) + [final_message]
            msg_model = usage_state.get("model", "gpt-4o")
            compact_pipeline = CompactionPipeline(model_name=msg_model)
            needs_compact, _ = compact_pipeline.needs_compaction(messages_for_budget)
            if needs_compact:
                return Command(
                    update={
                        "run_id": run_id,
                        "active_model": active_model,
                        "attempt_number": attempt_number,
                        "loop_count": loop_count,
                        "retry_index": 0,
                        "model_messages": [*model_messages, final_message],
                        "pending_tool_calls": [],
                        "pending_new_response": False,
                        "token_source": token_source or "fallback",
                        "fallback_final_text": fallback_final_text,
                        "final_text": final_text,
                        "usage_state": usage_state,
                        "usage_sources": usage_sources,
                        "usage_signature": next_signature,
                        "usage_payload": usage_payload,
                        "emitted_reasoning": emitted_reasoning,
                        "input_messages": messages_for_budget,
                        "structured_response": (
                            self.pipelines.structured_answer(final_text)
                            if request.output_format == "json"
                            else None
                        ),
                    },
                    goto="__compact__",
                )

            return Command(
                update={
                    "run_id": run_id,
                    "active_model": active_model,
                    "attempt_number": attempt_number,
                    "loop_count": loop_count,
                    "retry_index": 0,
                    "model_messages": [*model_messages, final_message],
                    "pending_tool_calls": [],
                    "pending_new_response": False,
                    "token_source": token_source or "fallback",
                    "fallback_final_text": fallback_final_text,
                    "final_text": final_text,
                    "usage_state": usage_state,
                    "usage_sources": usage_sources,
                    "usage_signature": next_signature,
                    "usage_payload": usage_payload,
                    "emitted_reasoning": emitted_reasoning,
                    "structured_response": (
                        self.pipelines.structured_answer(final_text)
                        if request.output_format == "json"
                        else None
                    ),
                },
                goto="finalize_success",
            )
        except Exception as exc:  # noqa: BLE001
            if retry_index < effective_runtime.agent_runtime.max_retries:
                await asyncio.sleep(0.5 * (2**retry_index))
                return Command(
                    update={
                        "run_id": "",
                        "attempt_number": attempt_number,
                        "retry_index": retry_index + 1,
                        "loop_count": 0,
                    },
                    goto="model_step",
                )

            failure_kind = classify_llm_failure(exc)
            has_more_candidates = candidate_index + 1 < len(route.candidates)
            if has_more_candidates and should_fallback_for_error(
                route.fallback_policy, failure_kind
            ):
                next_candidate = route.candidates[candidate_index + 1]
                self.services.append_llm_route_event(
                    runtime=runtime_state,
                    run_id=run_id,
                    session_id=request.session_id,
                    trigger_type=request.trigger_type,
                    event="llm_fallback_attempt",
                    details={
                        "from_profile": candidate.profile_name,
                        "to_profile": next_candidate.profile_name,
                        "failure_kind": failure_kind,
                        "error": str(exc),
                    },
                )
                return Command(
                    update={
                        "run_id": "",
                        "candidate_index": candidate_index + 1,
                        "retry_index": 0,
                        "pending_new_response": True,
                        "loop_count": 0,
                        "attempt_number": attempt_number,
                    },
                    goto="model_step",
                )

            self.services.append_llm_route_event(
                runtime=runtime_state,
                run_id=run_id,
                session_id=request.session_id,
                trigger_type=request.trigger_type,
                event="llm_route_exhausted",
                details={
                    "profile": candidate.profile_name,
                    "failure_kind": failure_kind,
                    "error": str(exc),
                },
            )
            error_code = (
                "max_steps_reached"
                if self._is_max_steps_error(exc)
                else "stream_failed"
            )
            return Command(
                update={
                    "run_id": run_id,
                    "attempt_number": attempt_number,
                    "error": RuntimeErrorInfo(
                        error=str(exc),
                        code=error_code,
                        run_id=run_id,
                        attempt=attempt_number,
                    ),
                },
                goto="finalize_error",
            )

    async def _tool_step(self, state: RuntimeGraphState) -> dict[str, Any]:
        request = state["request"]
        runtime_state = self.services.get_runtime(request.agent_id)
        hook_engine = self._resolve_hook_engine(request.agent_id)
        tool_service = ToolExecutionService.build(
            config_base_dir=self.services.require_base_dir(),
            runtime_root=runtime_state.root_dir,
            runtime=runtime_state.runtime_config,
            trigger_type=request.trigger_type,
            agent_id=request.agent_id,
            run_id=str(state.get("run_id", "")),
            session_id=request.session_id,
            runtime_audit_store=runtime_state.audit_store,
            hook_engine=hook_engine,
            explicit_enabled_tools=request.explicit_enabled_tools,
            explicit_blocked_tools=request.explicit_blocked_tools,
        )
        envelopes, tool_messages = await tool_service.execute_pending(
            list(state.get("pending_tool_calls", []))
        )
        for envelope in envelopes:
            self._emit(
                "tool_end",
                {
                    "run_id": str(state.get("run_id", "")),
                    "tool": envelope.tool,
                    "output": envelope.output,
                },
            )
        return {
            "model_messages": [*list(state.get("model_messages", [])), *tool_messages],
            "tool_history": envelopes,
            "pending_tool_calls": [],
            "pending_new_response": True,
        }

    def _finalize_success(self, state: RuntimeGraphState) -> dict[str, Any]:
        request = state["request"]
        self._emit(
            "done",
            {
                "content": str(state.get("final_text", "")),
                "session_id": request.session_id,
                "agent_id": request.agent_id,
                "run_id": str(state.get("run_id", "")),
                "token_source": str(state.get("token_source", "fallback") or "fallback"),
                "usage": dict(state.get("usage_payload", {})),
            },
        )

        # Stop hook (async)
        hook_engine = self._resolve_hook_engine(request.agent_id)
        if hook_engine and hook_engine.is_enabled:
            hook_event = HookEvent(
                hook_type="stop",
                agent_id=state["request"].agent_id,
                session_id=state["request"].session_id,
                run_id=state.get("run_id", ""),
                timestamp=self._hook_timestamp(),
                payload={
                    "status": "success",
                    "text_len": len(state.get("final_text", "")),
                },
            )
            hook_engine.dispatch_async(hook_event)
            self._append_hook_audit_event(
                trigger_type=request.trigger_type,
                hook_event=hook_event,
                status="dispatched",
                details={"result_status": "success", "text_len": len(state.get("final_text", ""))},
            )

        return {}

    def _compact_step(self, state: RuntimeGraphState) -> dict[str, Any]:
        """Compaction node: reduce message count when budget exceeded."""
        runtime = self.services.get_runtime(state["request"].agent_id)
        model_name = runtime.resolve_model_name() if hasattr(runtime, "resolve_model_name") else "gpt-4o"
        workspace = runtime.root_dir / "storage" / "checkpoints" if hasattr(runtime, "root_dir") else None

        pipeline = CompactionPipeline(
            model_name=model_name,
            checkpoint_dir=workspace,
        )

        messages = list(state.get("input_messages", []))

        # PreCompact hooks
        hook_engine = self._resolve_hook_engine(state["request"].agent_id)
        if hook_engine and hook_engine.is_enabled:
            hook_event = HookEvent(
                hook_type="pre_compact",
                agent_id=state["request"].agent_id,
                session_id=state["request"].session_id,
                run_id=str(state.get("run_id", "")),
                timestamp=self._hook_timestamp(),
                payload={"token_count": pipeline.count_messages_tokens(messages)},
            )
            hook_result = hook_engine.dispatch_sync(hook_event)
            self._append_hook_audit_event(
                trigger_type=state["request"].trigger_type,
                hook_event=hook_event,
                status="allow" if hook_result.allow else "deny",
                details={
                    "token_count": pipeline.count_messages_tokens(messages),
                    "reason": hook_result.reason,
                },
            )
            if not hook_result.allow:
                return {"compaction_deferred": True}

        # Create a summarize functor if we have an LLM available
        summarize_fn = None
        if hasattr(self, "pipelines") and hasattr(self.pipelines, "model"):
            try:
                from graph.lcel_compaction import build_summarize_pipeline
                summarize_fn = build_summarize_pipeline(self.pipelines.model)
            except Exception:
                pass

        # Run compaction in async context
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        result = loop.run_until_complete(
            pipeline.compact_round(
                messages,
                run_id=state.get("run_id", ""),
                step=state.get("loop_count", 0),
                summarize_fn=summarize_fn,
            )
        )

        # Distill to memory
        if result.summary and result.was_compacted and workspace:
            memory_file = runtime.root_dir / "memory" / "MEMORY.md"
            loop.run_until_complete(pipeline.distill(result.summary, memory_file=memory_file))

        self._emit("compaction", {
            "checkpoint_id": result.checkpoint_id,
            "was_compacted": result.was_compacted,
            "message_count_before": len(messages),
            "message_count_after": len(result.messages),
            "summary": result.summary.summary if result.summary else None,
        })

        return {
            "input_messages": result.messages,
            "last_checkpoint_id": result.checkpoint_id,
            "compaction_deferred": False,
        }

    def _finalize_error(self, state: RuntimeGraphState) -> dict[str, Any]:
        error = state.get("error")
        if isinstance(error, RuntimeErrorInfo):
            self._emit("error", error.as_payload())

        # Stop hook (async)
        hook_engine = self._resolve_hook_engine(state["request"].agent_id)
        if hook_engine and hook_engine.is_enabled:
            hook_event = HookEvent(
                hook_type="stop",
                agent_id=state["request"].agent_id,
                session_id=state["request"].session_id,
                run_id=state.get("run_id", ""),
                timestamp=self._hook_timestamp(),
                payload={
                    "status": "error",
                },
            )
            hook_engine.dispatch_async(hook_event)
            self._append_hook_audit_event(
                trigger_type=state["request"].trigger_type,
                hook_event=hook_event,
                status="dispatched",
                details={"result_status": "error"},
            )

        return {}
