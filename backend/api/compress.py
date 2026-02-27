from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from api.errors import ApiError
from graph.agent import AgentManager

router = APIRouter(tags=["compress"])

_AGENT_MANAGER: AgentManager | None = None


def set_agent_manager(agent_manager: AgentManager) -> None:
    global _AGENT_MANAGER
    _AGENT_MANAGER = agent_manager


def _require_agent_manager() -> AgentManager:
    if _AGENT_MANAGER is None:
        raise ApiError(status_code=500, code="not_initialized", message="Compress dependencies are not initialized")
    return _AGENT_MANAGER


@router.post("/sessions/{session_id}/compress")
async def compress_session(
    session_id: str,
    agent_id: str = Query(default="default", min_length=1, max_length=64),
) -> dict[str, Any]:
    agent_manager = _require_agent_manager()
    try:
        session_manager = agent_manager.get_session_manager(agent_id)
    except ValueError as exc:
        raise ApiError(status_code=400, code="invalid_request", message=str(exc)) from exc
    session = session_manager.load_session(session_id)
    messages: list[dict[str, Any]] = list(session.get("messages", []))

    if len(messages) < 4:
        raise ApiError(
            status_code=400,
            code="invalid_state",
            message="At least 4 messages are required for compression",
            details={"message_count": len(messages)},
        )

    n = max(4, len(messages) // 2)
    n = min(n, len(messages))

    summary = await agent_manager.summarize_messages(messages[:n])
    result = session_manager.compress_history(session_id=session_id, summary=summary, n=n)
    return {
        "data": {
            "session_id": session_id,
            "agent_id": agent_id,
            "archived_count": result["archived_count"],
            "remaining_count": result["remaining_count"],
            "summary": summary,
        }
    }
