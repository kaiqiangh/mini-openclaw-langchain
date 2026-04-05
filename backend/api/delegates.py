from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from api.errors import ApiError
from graph.agent import AgentManager
from tools.delegate_registry import DelegateRegistry, DelegateState

router = APIRouter(tags=["delegates"])

_agent_manager: AgentManager | None = None
_delegate_registry: DelegateRegistry | None = None


def set_agent_manager(agent_manager: AgentManager) -> None:
    global _agent_manager
    _agent_manager = agent_manager


def set_delegate_registry(registry: DelegateRegistry) -> None:
    global _delegate_registry
    _delegate_registry = registry


def _require_agent_manager() -> AgentManager:
    if _agent_manager is None:
        raise ApiError(
            status_code=500,
            code="not_initialized",
            message="Agent manager not initialized",
        )
    return _agent_manager


def _require_registry() -> DelegateRegistry:
    if _delegate_registry is None:
        raise ApiError(
            status_code=500,
            code="not_initialized",
            message="Delegate registry not initialized",
        )
    return _delegate_registry


def _ensure_session_exists(agent_id: str, session_id: str) -> None:
    manager = _require_agent_manager()
    try:
        runtime = manager.get_runtime(agent_id)
    except ValueError as exc:
        raise ApiError(
            status_code=400,
            code="invalid_request",
            message=str(exc),
        ) from exc
    session_path = runtime.session_manager.sessions_dir / f"{session_id}.json"
    if not session_path.exists():
        raise ApiError(status_code=404, code="not_found", message="Session not found")


def _state_summary(state: DelegateState) -> dict[str, Any]:
    return {
        "delegate_id": state.delegate_id,
        "role": state.role,
        "task": state.task,
        "status": state.status,
        "sub_session_id": state.sub_session_id,
        "created_at": state.created_at,
    }


def _state_detail(state: DelegateState) -> dict[str, Any]:
    payload = {
        **_state_summary(state),
        "agent_id": state.agent_id,
        "parent_session_id": state.parent_session_id,
        "allowed_tools": list(state.allowed_tools),
    }
    if state.blocked_tools:
        payload["blocked_tools"] = list(state.blocked_tools)
    if state.completed_at is not None:
        payload["completed_at"] = state.completed_at
    if state.duration_ms:
        payload["duration_ms"] = state.duration_ms
    if state.result_summary:
        payload["result_summary"] = state.result_summary
    if state.steps_completed:
        payload["steps_completed"] = state.steps_completed
    if state.tools_used:
        payload["tools_used"] = list(state.tools_used)
    if state.token_usage:
        payload["token_usage"] = dict(state.token_usage)
    if state.error_message:
        payload["error_message"] = state.error_message
    if state.result_dir is not None:
        payload["result_file"] = str(state.result_dir / "result_summary.md")
    return payload


def _require_delegate(
    registry: DelegateRegistry,
    *,
    agent_id: str,
    session_id: str,
    delegate_id: str,
) -> DelegateState:
    state = registry.get_status(delegate_id)
    if state is None:
        raise ApiError(status_code=404, code="not_found", message="Delegate not found")
    if state.agent_id != agent_id or state.parent_session_id != session_id:
        raise ApiError(status_code=404, code="not_found", message="Delegate not found")
    return state


@router.get("/agents/{agent_id}/sessions/{session_id}/delegates")
async def list_delegates(agent_id: str, session_id: str) -> dict[str, Any]:
    _ensure_session_exists(agent_id, session_id)
    registry = _require_registry()
    delegates = registry.list_for_session(agent_id, session_id)
    delegates.sort(key=lambda item: item.created_at, reverse=True)
    return {"delegates": [_state_summary(item) for item in delegates]}


@router.get("/agents/{agent_id}/sessions/{session_id}/delegates/{delegate_id}")
async def get_delegate(
    agent_id: str,
    session_id: str,
    delegate_id: str,
) -> dict[str, Any]:
    _ensure_session_exists(agent_id, session_id)
    registry = _require_registry()
    state = _require_delegate(
        registry,
        agent_id=agent_id,
        session_id=session_id,
        delegate_id=delegate_id,
    )
    return _state_detail(state)


@router.get("/agents/{agent_id}/sessions/{session_id}/delegates/{delegate_id}/stream")
async def stream_delegate(
    agent_id: str,
    session_id: str,
    delegate_id: str,
) -> StreamingResponse:
    _ensure_session_exists(agent_id, session_id)
    registry = _require_registry()

    async def event_generator():
        last_payload: dict[str, Any] | None = None
        while True:
            state = _require_delegate(
                registry,
                agent_id=agent_id,
                session_id=session_id,
                delegate_id=delegate_id,
            )
            payload = _state_detail(state)
            if payload != last_payload:
                last_payload = payload
                yield (
                    "event: delegate\n"
                    f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                )
            if state.status in {"completed", "failed", "timeout"}:
                break
            await asyncio.sleep(0.2)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )
