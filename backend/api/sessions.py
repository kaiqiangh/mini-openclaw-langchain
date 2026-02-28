from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from api.errors import ApiError
from graph.agent import AgentManager
from graph.session_manager import SessionManager

router = APIRouter(tags=["sessions"])

_agent_manager: AgentManager | None = None


def set_agent_manager(agent_manager: AgentManager) -> None:
    global _agent_manager
    _agent_manager = agent_manager


class CreateSessionRequest(BaseModel):
    title: str | None = Field(default=None, max_length=100)


class RenameSessionRequest(BaseModel):
    title: str = Field(min_length=1, max_length=100)


def _require_agent_manager() -> AgentManager:
    if _agent_manager is None:
        raise ApiError(
            status_code=500,
            code="not_initialized",
            message="Agent manager not initialized",
        )
    return _agent_manager


def _resolve_session_manager(agent_id: str) -> tuple[AgentManager, SessionManager]:
    manager = _require_agent_manager()
    try:
        session_manager = manager.get_session_manager(agent_id)
    except ValueError as exc:
        raise ApiError(
            status_code=400, code="invalid_request", message=str(exc)
        ) from exc
    return manager, session_manager


@router.get("/sessions")
async def list_sessions(
    scope: str = Query(default="active", pattern="^(active|archived|all)$"),
    agent_id: str = Query(default="default", min_length=1, max_length=64),
) -> dict[str, Any]:
    _, manager = _resolve_session_manager(agent_id)
    return {"data": manager.list_sessions(scope=scope)}


@router.post("/sessions")
async def create_session(
    request: CreateSessionRequest | None = None,
    agent_id: str = Query(default="default", min_length=1, max_length=64),
) -> dict[str, Any]:
    _, manager = _resolve_session_manager(agent_id)
    session_id = str(uuid.uuid4())
    payload = manager.load_session(session_id)

    if request and request.title:
        payload["title"] = request.title.strip()
        manager.save_session(session_id, payload)

    return {
        "data": {"session_id": session_id, "title": payload.get("title", "New Session")}
    }


@router.put("/sessions/{session_id}")
async def rename_session(
    session_id: str,
    req: RenameSessionRequest,
    agent_id: str = Query(default="default", min_length=1, max_length=64),
) -> dict[str, Any]:
    _, manager = _resolve_session_manager(agent_id)
    path = manager.sessions_dir / f"{session_id}.json"
    if not path.exists():
        raise ApiError(status_code=404, code="not_found", message="Session not found")

    session = manager.rename_session(session_id, req.title)
    return {"data": {"session_id": session_id, "title": session.get("title", "")}}


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    archived: bool = False,
    agent_id: str = Query(default="default", min_length=1, max_length=64),
) -> dict[str, Any]:
    _, manager = _resolve_session_manager(agent_id)
    deleted = manager.delete_session(session_id, archived=archived)
    if not deleted:
        raise ApiError(status_code=404, code="not_found", message="Session not found")
    return {"data": {"deleted": True, "session_id": session_id, "archived": archived}}


@router.post("/sessions/{session_id}/archive")
async def archive_session(
    session_id: str,
    agent_id: str = Query(default="default", min_length=1, max_length=64),
) -> dict[str, Any]:
    _, manager = _resolve_session_manager(agent_id)
    archived = manager.archive_session(session_id)
    if not archived:
        raise ApiError(status_code=404, code="not_found", message="Session not found")
    return {"data": {"archived": True, "session_id": session_id}}


@router.post("/sessions/{session_id}/restore")
async def restore_session(
    session_id: str,
    agent_id: str = Query(default="default", min_length=1, max_length=64),
) -> dict[str, Any]:
    _, manager = _resolve_session_manager(agent_id)
    restored = manager.restore_session(session_id)
    if not restored:
        raise ApiError(
            status_code=404, code="not_found", message="Archived session not found"
        )
    return {"data": {"restored": True, "session_id": session_id}}


@router.get("/sessions/{session_id}/messages")
async def get_messages(
    session_id: str,
    archived: bool = False,
    agent_id: str = Query(default="default", min_length=1, max_length=64),
) -> dict[str, Any]:
    agent, manager = _resolve_session_manager(agent_id)

    try:
        session = manager.load_session(session_id, archived=archived)
    except FileNotFoundError as exc:
        raise ApiError(status_code=404, code="not_found", message=str(exc)) from exc
    if agent.config is None:
        raise ApiError(
            status_code=500,
            code="not_initialized",
            message="Agent config is unavailable",
        )
    runtime = agent.get_runtime(agent_id)

    system_prompt = agent.build_system_prompt(
        rag_mode=runtime.runtime_config.rag_mode,
        is_first_turn=len(session.get("messages", [])) == 0,
        agent_id=agent_id,
    )
    return {
        "data": {
            "session_id": session_id,
            "agent_id": agent_id,
            "archived": archived,
            "system_prompt": system_prompt,
            "messages": manager.with_live_response(
                list(session.get("messages", [])),
                session,
            ),
            "compressed_context": session.get("compressed_context", ""),
        }
    }


@router.get("/sessions/{session_id}/history")
async def get_history(
    session_id: str,
    archived: bool = False,
    agent_id: str = Query(default="default", min_length=1, max_length=64),
) -> dict[str, Any]:
    _, manager = _resolve_session_manager(agent_id)
    try:
        session = manager.load_session(session_id, archived=archived)
    except FileNotFoundError as exc:
        raise ApiError(status_code=404, code="not_found", message=str(exc)) from exc
    return {
        "data": {
            "session_id": session_id,
            "agent_id": agent_id,
            "archived": archived,
            "messages": manager.with_live_response(
                list(session.get("messages", [])),
                session,
            ),
            "compressed_context": session.get("compressed_context", ""),
        }
    }


@router.post("/sessions/{session_id}/generate-title")
async def generate_title(
    session_id: str,
    agent_id: str = Query(default="default", min_length=1, max_length=64),
) -> dict[str, Any]:
    agent, manager = _resolve_session_manager(agent_id)
    session = manager.load_session(session_id)

    messages = session.get("messages", [])
    seed = ""
    if messages:
        for msg in messages:
            if msg.get("role") == "user":
                seed = str(msg.get("content", "")).strip()
                if seed:
                    break
        if not seed:
            seed = str(messages[0].get("content", "")).strip()

    if not seed:
        seed = str(session.get("compressed_context", "")).strip()

    if not seed:
        raise ApiError(
            status_code=400,
            code="invalid_state",
            message="Cannot generate title for empty session",
        )

    title = await agent.generate_title(seed, agent_id=agent_id)
    manager.update_title(session_id, title)
    return {"data": {"session_id": session_id, "title": title}}
