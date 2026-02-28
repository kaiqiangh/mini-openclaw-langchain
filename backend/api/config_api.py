from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel

from api.errors import ApiError
from config import load_config, load_runtime_config, save_runtime_config, save_runtime_config_to_path
from graph.agent import AgentManager

router = APIRouter(tags=["config"])

_BASE_DIR: Path | None = None
_AGENT_MANAGER: AgentManager | None = None


class RagModeRequest(BaseModel):
    enabled: bool


def set_base_dir(base_dir: Path) -> None:
    global _BASE_DIR
    _BASE_DIR = base_dir


def set_agent_manager(agent_manager: AgentManager) -> None:
    global _AGENT_MANAGER
    _AGENT_MANAGER = agent_manager


def set_dependencies(base_dir: Path, agent_manager: AgentManager) -> None:
    set_base_dir(base_dir)
    set_agent_manager(agent_manager)


def _require_base_dir() -> Path:
    if _BASE_DIR is None:
        raise ApiError(status_code=500, code="not_initialized", message="Config base directory is unavailable")
    return _BASE_DIR


@router.get("/config/rag-mode")
async def get_rag_mode(
    agent_id: str = Query(default="default", min_length=1, max_length=64),
) -> dict[str, Any]:
    base_dir = _require_base_dir()
    if _AGENT_MANAGER is None:
        config = load_config(base_dir)
        return {"data": {"enabled": config.runtime.rag_mode, "agent_id": "default"}}
    try:
        runtime = _AGENT_MANAGER.get_runtime(agent_id)
    except ValueError as exc:
        raise ApiError(status_code=400, code="invalid_request", message=str(exc)) from exc
    return {"data": {"enabled": runtime.runtime_config.rag_mode, "agent_id": runtime.agent_id}}


@router.put("/config/rag-mode")
async def set_rag_mode(
    request: RagModeRequest,
    agent_id: str = Query(default="default", min_length=1, max_length=64),
) -> dict[str, Any]:
    base_dir = _require_base_dir()
    if _AGENT_MANAGER is None:
        config = load_config(base_dir)
        config.runtime.rag_mode = request.enabled
        save_runtime_config(base_dir, config.runtime)
        return {"data": {"enabled": request.enabled, "agent_id": "default"}}
    try:
        agent_config_path = _AGENT_MANAGER.get_agent_config_path(agent_id)
        runtime = load_runtime_config(agent_config_path)
        runtime.rag_mode = request.enabled
        save_runtime_config_to_path(agent_config_path, runtime)
        refreshed = _AGENT_MANAGER.get_runtime(agent_id)
    except ValueError as exc:
        raise ApiError(status_code=400, code="invalid_request", message=str(exc)) from exc
    return {"data": {"enabled": refreshed.runtime_config.rag_mode, "agent_id": refreshed.agent_id}}
