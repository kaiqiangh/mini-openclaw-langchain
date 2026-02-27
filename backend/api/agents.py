from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from api.errors import ApiError
from graph.agent import AgentManager

router = APIRouter(tags=["agents"])

_agent_manager: AgentManager | None = None


class CreateAgentRequest(BaseModel):
    agent_id: str = Field(min_length=1, max_length=64)


def set_agent_manager(agent_manager: AgentManager) -> None:
    global _agent_manager
    _agent_manager = agent_manager


def _require_agent_manager() -> AgentManager:
    if _agent_manager is None:
        raise ApiError(status_code=500, code="not_initialized", message="Agent manager is not initialized")
    return _agent_manager


@router.get("/agents")
async def list_agents() -> dict[str, Any]:
    manager = _require_agent_manager()
    return {"data": manager.list_agents()}


@router.post("/agents")
async def create_agent(req: CreateAgentRequest) -> dict[str, Any]:
    manager = _require_agent_manager()
    try:
        created = manager.create_agent(req.agent_id)
    except ValueError as exc:
        raise ApiError(status_code=400, code="invalid_request", message=str(exc)) from exc
    return {"data": created}


@router.delete("/agents/{agent_id}")
async def delete_agent(agent_id: str) -> dict[str, Any]:
    manager = _require_agent_manager()
    try:
        deleted = manager.delete_agent(agent_id)
    except ValueError as exc:
        raise ApiError(status_code=400, code="invalid_request", message=str(exc)) from exc
    if not deleted:
        raise ApiError(status_code=404, code="not_found", message="Agent not found")
    return {"data": {"deleted": True, "agent_id": agent_id}}
