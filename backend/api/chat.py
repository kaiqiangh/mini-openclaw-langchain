from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from api.errors import ApiError
from graph.agent import AgentManager

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    agent_id: str = Field(default="default", min_length=1, max_length=64)
    stream: bool = True


@dataclass
class _StreamRunState:
    key: str
    agent_id: str
    session_id: str
    message: str
    is_first_turn: bool
    subscribers: set[asyncio.Queue[dict[str, str] | None]] = field(default_factory=set)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    task: asyncio.Task[None] | None = None
    done: bool = False
    run_id: str = ""
    assistant_segments: list[dict[str, Any]] = field(default_factory=list)
    current_content: str = ""
    current_tool_calls: list[dict[str, Any]] = field(default_factory=list)
    last_live_sync_ms: int = 0


_agent_manager: AgentManager | None = None
_active_runs: dict[str, _StreamRunState] = {}
_active_runs_lock = asyncio.Lock()


def set_agent_manager(agent_manager: AgentManager) -> None:
    global _agent_manager
    _agent_manager = agent_manager


def _require_agent_manager() -> AgentManager:
    if _agent_manager is None or _agent_manager.session_manager is None:
        raise ApiError(
            status_code=500,
            code="not_initialized",
            message="Agent manager is not initialized",
        )
    return _agent_manager


def _run_key(agent_id: str, session_id: str) -> str:
    return f"{agent_id}:{session_id}"


def _snapshot_live_content(state: _StreamRunState) -> str:
    content_parts: list[str] = []
    for segment in state.assistant_segments:
        text = str(segment.get("content", "")).strip()
        if text:
            content_parts.append(text)
    current = state.current_content.strip()
    if current:
        content_parts.append(current)
    return "\n\n".join(content_parts).strip()


def _flush_current_segment(state: _StreamRunState, fallback_content: str = "") -> None:
    content = state.current_content.strip() or fallback_content.strip()
    if content or state.current_tool_calls:
        state.assistant_segments.append(
            {
                "content": content,
                "tool_calls": list(state.current_tool_calls),
            }
        )
    state.current_content = ""
    state.current_tool_calls = []


def _persist_live_snapshot(
    session_manager: Any, state: _StreamRunState, *, force: bool = False
) -> None:
    now_ms = int(time.time() * 1000)
    if not force and now_ms - state.last_live_sync_ms < 350:
        return

    content = _snapshot_live_content(state)
    tool_calls = list(state.current_tool_calls)
    if not content and not tool_calls:
        return

    session_manager.set_live_response(
        state.session_id,
        run_id=state.run_id or "__pending__",
        content=content,
        tool_calls=tool_calls or None,
    )
    state.last_live_sync_ms = now_ms


async def _publish_event(
    state: _StreamRunState, event_type: str, data: dict[str, Any] | str
) -> None:
    payload = {
        "event": event_type,
        "data": json.dumps(data, ensure_ascii=False),
    }

    async with state.lock:
        subscribers = list(state.subscribers)

    for queue in subscribers:
        try:
            queue.put_nowait(payload)
            continue
        except asyncio.QueueFull:
            pass

        # Keep the newest event by dropping one stale entry if queue is saturated.
        try:
            _ = queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:
            continue


async def _close_run(state: _StreamRunState) -> None:
    async with state.lock:
        if state.done:
            return
        state.done = True
        subscribers = list(state.subscribers)
        state.subscribers.clear()

    for queue in subscribers:
        try:
            queue.put_nowait(None)
        except asyncio.QueueFull:
            pass

    async with _active_runs_lock:
        current = _active_runs.get(state.key)
        if current is state:
            _active_runs.pop(state.key, None)


async def _persist_final_segments(state: _StreamRunState, runtime: Any) -> None:
    session_manager = runtime.session_manager
    session_manager.clear_live_response(state.session_id, run_id=state.run_id or None)

    for idx, segment in enumerate(state.assistant_segments):
        content = str(segment.get("content", "")).strip()
        if not content:
            continue
        tool_calls = segment.get("tool_calls") or None
        session_manager.save_message(
            state.session_id,
            "assistant",
            content,
            tool_calls=tool_calls,
        )
        if runtime.audit_store is not None:
            runtime.audit_store.append_message_link(
                run_id=state.run_id or None,
                session_id=state.session_id,
                role="assistant",
                segment_index=idx,
                content=content,
                details={"tool_call_count": len(tool_calls or [])},
            )


async def _run_stream_task(
    state: _StreamRunState,
    *,
    agent: AgentManager,
    runtime: Any,
    history: list[dict[str, Any]],
) -> None:
    session_manager = runtime.session_manager
    persisted_final = False

    try:
        # Persist user input immediately so generation can continue independently of client SSE.
        session_manager.save_message(state.session_id, "user", state.message)
        if runtime.audit_store is not None:
            runtime.audit_store.append_message_link(
                run_id=None,
                session_id=state.session_id,
                role="user",
                segment_index=0,
                content=state.message,
                details={"source": "chat_persist"},
            )

        async for event in agent.astream(
            message=state.message,
            history=history,
            session_id=state.session_id,
            is_first_turn=state.is_first_turn,
            trigger_type="chat",
            agent_id=state.agent_id,
        ):
            event_type = str(event.get("type", "message"))
            raw_data = event.get("data", {})
            data = raw_data if isinstance(raw_data, dict) else {"value": raw_data}

            if event_type == "run_start":
                run_id = str(data.get("run_id", "")).strip()
                if run_id:
                    state.run_id = run_id
                    _persist_live_snapshot(session_manager, state, force=True)

            if event_type == "token":
                state.current_content += str(data.get("content", ""))
                _persist_live_snapshot(session_manager, state, force=False)

            if event_type == "tool_start":
                state.current_tool_calls.append(
                    {
                        "tool": data.get("tool", "tool"),
                        "input": data.get("input", {}),
                    }
                )
                _persist_live_snapshot(session_manager, state, force=True)

            if event_type == "tool_end" and state.current_tool_calls:
                state.current_tool_calls[-1]["output"] = data.get("output", "")
                _persist_live_snapshot(session_manager, state, force=True)

            if event_type == "new_response":
                _flush_current_segment(state)
                _persist_live_snapshot(session_manager, state, force=True)

            pending_title: str | None = None
            if event_type == "done":
                done_content = str(data.get("content", "")).strip()
                _flush_current_segment(state, fallback_content=done_content)
                await _persist_final_segments(state, runtime)
                persisted_final = True
                if state.is_first_turn:
                    title = await agent.generate_title(
                        state.message,
                        agent_id=state.agent_id,
                    )
                    session_manager.update_title(state.session_id, title)
                    pending_title = title

            await _publish_event(state, event_type, data)

            if event_type == "done" and pending_title:
                await _publish_event(
                    state,
                    "title",
                    {
                        "session_id": state.session_id,
                        "agent_id": state.agent_id,
                        "title": pending_title,
                    },
                )

        if not persisted_final:
            _flush_current_segment(state)
            if state.assistant_segments:
                await _persist_final_segments(state, runtime)

    except Exception as exc:  # noqa: BLE001
        session_manager.clear_live_response(state.session_id, run_id=state.run_id or None)
        await _publish_event(
            state,
            "error",
            {
                "error": str(exc),
                "run_id": state.run_id,
                "attempt": 1,
            },
        )
    finally:
        await _close_run(state)


async def _subscribe_run(state: _StreamRunState) -> asyncio.Queue[dict[str, str] | None]:
    queue: asyncio.Queue[dict[str, str] | None] = asyncio.Queue(maxsize=512)
    async with state.lock:
        if state.done:
            queue.put_nowait(None)
            return queue
        state.subscribers.add(queue)
    return queue


async def _unsubscribe_run(
    state: _StreamRunState,
    queue: asyncio.Queue[dict[str, str] | None],
) -> None:
    async with state.lock:
        state.subscribers.discard(queue)


@router.post("/chat")
async def chat(request: ChatRequest) -> Any:
    agent = _require_agent_manager()
    try:
        runtime = agent.get_runtime(request.agent_id)
        session_manager = runtime.session_manager
    except ValueError as exc:
        raise ApiError(
            status_code=400, code="invalid_request", message=str(exc)
        ) from exc

    session = session_manager.load_session(request.session_id)
    is_first_turn = len(session.get("messages", [])) == 0
    history = session_manager.load_session_for_agent(request.session_id)

    if not request.stream:
        result = await agent.run_once(
            message=request.message,
            history=history,
            session_id=request.session_id,
            is_first_turn=is_first_turn,
            output_format="text",
            trigger_type="chat",
            agent_id=request.agent_id,
        )
        text = str(result.get("text", ""))
        usage = result.get("usage", {})
        session_manager.save_message(request.session_id, "user", request.message)
        session_manager.save_message(request.session_id, "assistant", text)
        return {
            "data": {
                "content": text,
                "session_id": request.session_id,
                "agent_id": request.agent_id,
                "usage": usage,
            }
        }

    key = _run_key(request.agent_id, request.session_id)
    start_task = False

    async with _active_runs_lock:
        state = _active_runs.get(key)
        if state is not None and state.done:
            _active_runs.pop(key, None)
            state = None

        if state is None:
            state = _StreamRunState(
                key=key,
                agent_id=request.agent_id,
                session_id=request.session_id,
                message=request.message,
                is_first_turn=is_first_turn,
            )
            _active_runs[key] = state
            start_task = True
        elif state.message.strip() != request.message.strip():
            raise ApiError(
                status_code=409,
                code="session_busy",
                message="A streaming run is already active for this session.",
            )

    queue = await _subscribe_run(state)

    if start_task:
        state.task = asyncio.create_task(
            _run_stream_task(
                state,
                agent=agent,
                runtime=runtime,
                history=history,
            )
        )

    async def event_generator():
        try:
            while True:
                payload = await queue.get()
                if payload is None:
                    break
                yield payload
        finally:
            await _unsubscribe_run(state, queue)

    return EventSourceResponse(event_generator())
