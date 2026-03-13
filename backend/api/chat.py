from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from api.errors import ApiError
from control import LocalCoordinator
from graph.agent import AgentManager

router = APIRouter(tags=["chat"])
logger = logging.getLogger(__name__)
_SKILL_PATH_PATTERN = re.compile(
    r"(?:^|[^A-Za-z0-9._-])(?:\./)?skills/([A-Za-z0-9._-]+)(?=/)"
)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    stream: bool = True
    resume_same_turn: bool = False


@dataclass
class _StreamRunState:
    key: str
    agent_id: str
    session_id: str
    message: str
    is_first_turn: bool
    resume_same_turn: bool = False
    history: list[dict[str, Any]] = field(default_factory=list)
    subscribers: set[asyncio.Queue[dict[str, str] | None]] = field(default_factory=set)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    task: asyncio.Task[None] | None = None
    done: bool = False
    lock_owner: str = ""


_agent_manager: AgentManager | None = None
_coordinator: LocalCoordinator | None = None
_active_runs: dict[str, _StreamRunState] = {}
_active_runs_lock = asyncio.Lock()


def set_agent_manager(agent_manager: AgentManager) -> None:
    global _agent_manager
    _agent_manager = agent_manager


def set_coordinator(coordinator: LocalCoordinator) -> None:
    global _coordinator
    _coordinator = coordinator


def _require_agent_manager() -> AgentManager:
    if _agent_manager is None:
        raise ApiError(
            status_code=500,
            code="not_initialized",
            message="Agent manager is not initialized",
        )
    return _agent_manager


def _run_key(agent_id: str, session_id: str) -> str:
    return f"{agent_id}:{session_id}"


def _extract_skill_uses(value: Any) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()

    def visit(node: Any) -> None:
        if isinstance(node, str):
            for match in _SKILL_PATH_PATTERN.finditer(node):
                skill_name = str(match.group(1)).strip()
                if not skill_name or skill_name in seen:
                    continue
                seen.add(skill_name)
                found.append(skill_name)
            return
        if isinstance(node, dict):
            for child in node.values():
                visit(child)
            return
        if isinstance(node, (list, tuple, set)):
            for child in node:
                visit(child)

    visit(value)
    return found


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
    if _coordinator is not None and state.lock_owner:
        _coordinator.release_stream_lock(state.key, state.lock_owner)


async def _run_stream_task(
    state: _StreamRunState,
    *,
    agent: AgentManager,
) -> None:
    try:
        async for event in agent.astream(
            message=state.message,
            history=state.history,
            session_id=state.session_id,
            is_first_turn=state.is_first_turn,
            trigger_type="chat",
            agent_id=state.agent_id,
            resume_same_turn=state.resume_same_turn,
        ):
            event_type = str(event.get("type", "message"))
            raw_data = event.get("data", {})
            data = raw_data if isinstance(raw_data, dict) else {"value": raw_data}
            if event_type == "tool_start":
                skill_uses = _extract_skill_uses(data.get("input", {}))
                if skill_uses:
                    data = {**data, "skill_uses": skill_uses}

            await _publish_event(state, event_type, data)

            if event_type == "done" and state.is_first_turn:
                title = await agent.generate_title(state.message, agent_id=state.agent_id)
                agent.get_session_manager(state.agent_id).update_title(
                    state.session_id, title
                )
                await _publish_event(
                    state,
                    "title",
                    {
                        "session_id": state.session_id,
                        "agent_id": state.agent_id,
                        "title": title,
                    },
                )
    except Exception:  # noqa: BLE001
        logger.exception(
            "Chat stream failed",
            extra={
                "agent_id": state.agent_id,
                "session_id": state.session_id,
            },
        )
        await _publish_event(
            state,
            "error",
            {
                "error": "Stream failed. Check server logs for details.",
                "code": "stream_failed",
                "run_id": "",
                "attempt": 1,
            },
        )
    finally:
        await _close_run(state)


async def _subscribe_run(
    state: _StreamRunState,
) -> asyncio.Queue[dict[str, str] | None]:
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


@router.post("/agents/{agent_id}/chat")
async def chat(agent_id: str, request: ChatRequest) -> Any:
    agent = _require_agent_manager()
    try:
        agent.get_session_manager(agent_id)
    except ValueError as exc:
        raise ApiError(
            status_code=400, code="invalid_request", message=str(exc)
        ) from exc

    session_repository = agent.get_session_repository(agent_id)
    snapshot = await session_repository.load_snapshot(
        agent_id=agent_id,
        session_id=request.session_id,
        include_live=False,
        create_if_missing=True,
    )
    is_first_turn = len(snapshot.messages) == 0
    history = await session_repository.load_history_for_agent(
        agent_id=agent_id,
        session_id=request.session_id,
        create_if_missing=True,
    )
    if request.resume_same_turn and history:
        last = history[-1]
        if (
            str(last.get("role", "")).strip() == "user"
            and str(last.get("content", "")).strip() == request.message.strip()
        ):
            history = history[:-1]

    if not request.stream:
        result = await agent.run_once(
            message=request.message,
            history=history,
            session_id=request.session_id,
            is_first_turn=is_first_turn,
            output_format="text",
            trigger_type="chat",
            agent_id=agent_id,
        )
        return {
            "data": {
                "content": str(result.get("text", "")),
                "session_id": request.session_id,
                "agent_id": agent_id,
                "selected_skills": [
                    str(item).strip()
                    for item in result.get("selected_skills", [])
                    if str(item).strip()
                ],
                "usage": result.get("usage", {}),
            }
        }

    key = _run_key(agent_id, request.session_id)
    start_task = False
    lock_owner = ""

    async with _active_runs_lock:
        state = _active_runs.get(key)
        if state is not None and state.done:
            _active_runs.pop(key, None)
            state = None

        if state is None:
            if _coordinator is not None:
                lock_owner = str(uuid.uuid4())
                acquired = _coordinator.acquire_stream_lock(
                    key, lock_owner, ttl_seconds=300
                )
                if not acquired:
                    raise ApiError(
                        status_code=409,
                        code="session_busy",
                        message="A streaming run is already active for this session.",
                    )
            state = _StreamRunState(
                key=key,
                agent_id=agent_id,
                session_id=request.session_id,
                message=request.message,
                is_first_turn=is_first_turn,
                resume_same_turn=bool(request.resume_same_turn),
                history=history,
                lock_owner=lock_owner,
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
