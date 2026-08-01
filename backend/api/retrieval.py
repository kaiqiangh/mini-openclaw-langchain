from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter

from api.agent_guard import require_existing_runtime
from api.errors import ApiError
from graph.agent import AgentManager
from tools.search_knowledge_tool import SearchKnowledgeTool

router = APIRouter(tags=["retrieval"])
_AGENT_MANAGER: AgentManager | None = None


def set_agent_manager(agent_manager: AgentManager) -> None:
    global _AGENT_MANAGER
    _AGENT_MANAGER = agent_manager


@router.get("/agents/{agent_id}/retrieval/status")
async def retrieval_status(agent_id: str) -> dict[str, Any]:
    if _AGENT_MANAGER is None:
        raise ApiError(status_code=500, code="not_initialized", message="Retrieval is not initialized")
    try:
        runtime = require_existing_runtime(_AGENT_MANAGER, agent_id)
    except ValueError as exc:
        raise ApiError(status_code=400, code="invalid_request", message=str(exc)) from exc

    knowledge = SearchKnowledgeTool(
        root_dir=runtime.root_dir,
        config_base_dir=Path(_AGENT_MANAGER.base_dir or runtime.root_dir),
    )
    return {
        "data": {
            "agent_id": runtime.agent_id,
            "memory": runtime.memory_indexer.status(),
            "knowledge": knowledge.status(),
        }
    }
