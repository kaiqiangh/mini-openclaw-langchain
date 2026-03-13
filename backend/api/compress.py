from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from api.errors import ApiError
from graph.agent import AgentManager
from graph.session_manager import LegacySessionStateError

router = APIRouter(tags=["compress"])

_AGENT_MANAGER: AgentManager | None = None


def set_agent_manager(agent_manager: AgentManager) -> None:
    global _AGENT_MANAGER
    _AGENT_MANAGER = agent_manager


def _require_agent_manager() -> AgentManager:
    if _AGENT_MANAGER is None:
        raise ApiError(
            status_code=500,
            code="not_initialized",
            message="Compress dependencies are not initialized",
        )
    return _AGENT_MANAGER


def _legacy_state_api_error(exc: LegacySessionStateError) -> ApiError:
    return ApiError(
        status_code=409,
        code="unsupported_legacy_state",
        message=str(exc),
    )


@router.post("/agents/{agent_id}/sessions/{session_id}/compress")
async def compress_session(
    agent_id: str,
    session_id: str,
) -> dict[str, Any]:
    agent_manager = _require_agent_manager()
    try:
        agent_manager.get_runtime(agent_id)
    except ValueError as exc:
        raise ApiError(
            status_code=400, code="invalid_request", message=str(exc)
        ) from exc
    repository = agent_manager.get_session_repository(agent_id)
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
    messages = list(snapshot.messages)

    if len(messages) < 4:
        raise ApiError(
            status_code=400,
            code="invalid_state",
            message="At least 4 messages are required for compression",
            details={"message_count": len(messages)},
        )

    n = max(4, len(messages) // 2)
    n = min(n, len(messages))

    summary = await agent_manager.summarize_messages(messages[:n], agent_id=agent_id)
    result = await repository.compress_history(
        agent_id=agent_id,
        session_id=session_id,
        summary=summary,
        n=n,
    )
    return {
        "data": {
            "session_id": session_id,
            "agent_id": agent_id,
            "archived_count": result["archived_count"],
            "remaining_count": result["remaining_count"],
            "summary": summary,
        }
    }
