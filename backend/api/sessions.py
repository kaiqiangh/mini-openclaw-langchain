from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Query, Response, status
from pydantic import BaseModel, Field

from api.errors import ApiError
from graph.agent import AgentManager
from graph.session_manager import LegacySessionStateError, SessionManager

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
        session_manager = manager.get_runtime(agent_id).session_manager
    except ValueError as exc:
        raise ApiError(
            status_code=400, code="invalid_request", message=str(exc)
        ) from exc
    return manager, session_manager


def _cron_session_titles(agent_manager: AgentManager, agent_id: str) -> dict[str, str]:
    """Get cron job titles from the existing scheduler instance if available."""
    from api import scheduler_api

    scheduler = scheduler_api.get_cron_scheduler(agent_id)
    if scheduler is None:
        return {}
    return {
        job.id: job.name.strip()
        for job in scheduler.list_jobs()
        if job.id and job.name.strip()
    }


def _display_session_title(
    session_id: str,
    title: str,
    *,
    cron_titles: dict[str, str],
) -> str:
    normalized = title.strip()
    if normalized and normalized != "New Session":
        return normalized
    if session_id.startswith("__cron__:"):
        job_id = session_id.split(":", 1)[1].strip()
        cron_title = cron_titles.get(job_id, "").strip()
        if cron_title:
            return cron_title
    return normalized or "New Session"


def _legacy_state_api_error(exc: LegacySessionStateError) -> ApiError:
    return ApiError(
        status_code=409,
        code="unsupported_legacy_state",
        message=str(exc),
    )


@router.get("/agents/{agent_id}/sessions")
async def list_sessions(
    agent_id: str,
    scope: str = Query(default="active", pattern="^(active|archived|all)$"),
) -> dict[str, Any]:
    agent_manager, session_manager = _resolve_session_manager(agent_id)
    cron_titles = _cron_session_titles(agent_manager, agent_id)
    try:
        raw_sessions = await session_manager.list_sessions(scope=scope)
    except LegacySessionStateError as exc:
        raise _legacy_state_api_error(exc) from exc
    sessions = []
    for item in raw_sessions:
        row = dict(item)
        row["title"] = _display_session_title(
            str(row.get("session_id", "")),
            str(row.get("title", "")),
            cron_titles=cron_titles,
        )
        sessions.append(row)
    return {"data": sessions}


@router.post("/agents/{agent_id}/sessions", status_code=status.HTTP_201_CREATED)
async def create_session(
    agent_id: str,
    response: Response,
    request: CreateSessionRequest | None = None,
) -> dict[str, Any]:
    _, manager = _resolve_session_manager(agent_id)
    session_id = str(uuid.uuid4())
    title = request.title if request and request.title else "New Session"
    payload = await manager.create_session(session_id, title=title)

    response.headers["Location"] = f"/api/v1/agents/{agent_id}/sessions/{session_id}"
    return {
        "data": {"session_id": session_id, "title": payload.get("title", "New Session")}
    }


@router.put("/agents/{agent_id}/sessions/{session_id}")
async def rename_session(
    agent_id: str,
    session_id: str,
    req: RenameSessionRequest,
) -> dict[str, Any]:
    _, manager = _resolve_session_manager(agent_id)
    path = manager.sessions_dir / f"{session_id}.json"
    if not path.exists():
        raise ApiError(status_code=404, code="not_found", message="Session not found")

    session = await manager.rename_session(session_id, req.title)
    return {"data": {"session_id": session_id, "title": session.get("title", "")}}


@router.delete(
    "/agents/{agent_id}/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_session(
    agent_id: str,
    session_id: str,
    archived: bool = False,
) -> Response:
    agent_manager, _ = _resolve_session_manager(agent_id)
    repository = agent_manager.get_session_repository(agent_id)
    deleted = await repository.delete_session(
        agent_id=agent_id,
        session_id=session_id,
        archived=archived,
    )
    if not deleted:
        raise ApiError(status_code=404, code="not_found", message="Session not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/agents/{agent_id}/sessions/{session_id}/archive")
async def archive_session(
    agent_id: str,
    session_id: str,
) -> dict[str, Any]:
    _, manager = _resolve_session_manager(agent_id)
    archived = await manager.archive_session(session_id)
    if not archived:
        raise ApiError(status_code=404, code="not_found", message="Session not found")
    return {"data": {"archived": True, "session_id": session_id}}


@router.post("/agents/{agent_id}/sessions/{session_id}/restore")
async def restore_session(
    agent_id: str,
    session_id: str,
) -> dict[str, Any]:
    _, manager = _resolve_session_manager(agent_id)
    restored = await manager.restore_session(session_id)
    if not restored:
        raise ApiError(
            status_code=404, code="not_found", message="Archived session not found"
        )
    return {"data": {"restored": True, "session_id": session_id}}


@router.get("/agents/{agent_id}/sessions/{session_id}/messages")
async def get_messages(
    agent_id: str,
    session_id: str,
    archived: bool = False,
) -> dict[str, Any]:
    agent, _ = _resolve_session_manager(agent_id)
    repository = agent.get_session_repository(agent_id)
    try:
        canonical = await repository.load_snapshot(
            agent_id=agent_id,
            session_id=session_id,
            archived=archived,
            include_live=not archived,
        )
    except FileNotFoundError as exc:
        raise ApiError(status_code=404, code="not_found", message=str(exc)) from exc
    except LegacySessionStateError as exc:
        raise _legacy_state_api_error(exc) from exc
    canonical_messages = canonical.messages
    compressed_context = canonical.compressed_context
    is_first_turn = len(canonical.messages) == 0
    if agent.config is None:
        raise ApiError(
            status_code=500,
            code="not_initialized",
            message="Agent config is unavailable",
        )
    runtime = agent.get_runtime(agent_id)

    system_prompt = agent.build_system_prompt(
        rag_mode=runtime.runtime_config.rag_mode,
        is_first_turn=is_first_turn,
        agent_id=agent_id,
    )
    return {
        "data": {
            "session_id": session_id,
            "agent_id": agent_id,
            "archived": archived,
            "system_prompt": system_prompt,
            "messages": canonical_messages,
            "compressed_context": compressed_context,
        }
    }


@router.get("/agents/{agent_id}/sessions/{session_id}/history")
async def get_history(
    agent_id: str,
    session_id: str,
    archived: bool = False,
) -> dict[str, Any]:
    agent, _ = _resolve_session_manager(agent_id)
    repository = agent.get_session_repository(agent_id)
    try:
        canonical = await repository.load_snapshot(
            agent_id=agent_id,
            session_id=session_id,
            archived=archived,
            include_live=not archived,
        )
    except FileNotFoundError as exc:
        raise ApiError(status_code=404, code="not_found", message=str(exc)) from exc
    except LegacySessionStateError as exc:
        raise _legacy_state_api_error(exc) from exc
    messages = canonical.messages
    compressed_context = canonical.compressed_context
    return {
        "data": {
            "session_id": session_id,
            "agent_id": agent_id,
            "archived": archived,
            "messages": messages,
            "compressed_context": compressed_context,
        }
    }


@router.post("/agents/{agent_id}/sessions/{session_id}/generate-title")
async def generate_title(
    agent_id: str,
    session_id: str,
) -> dict[str, Any]:
    agent, manager = _resolve_session_manager(agent_id)
    repository = agent.get_session_repository(agent_id)
    try:
        snapshot = await repository.load_snapshot(
            agent_id=agent_id,
            session_id=session_id,
            include_live=False,
        )
    except FileNotFoundError as exc:
        raise ApiError(status_code=404, code="not_found", message=str(exc)) from exc
    except LegacySessionStateError as exc:
        raise _legacy_state_api_error(exc) from exc
    messages = snapshot.messages
    compressed_context = snapshot.compressed_context.strip()
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
        seed = compressed_context

    if not seed:
        raise ApiError(
            status_code=400,
            code="invalid_state",
            message="Cannot generate title for empty session",
        )

    title = await agent.generate_title(seed, agent_id=agent_id)
    await manager.update_title(session_id, title)
    return {"data": {"session_id": session_id, "title": title}}
