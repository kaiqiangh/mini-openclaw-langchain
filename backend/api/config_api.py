from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel

from api.errors import ApiError
from config import (
    load_config,
    load_runtime_config,
    runtime_from_payload,
    runtime_to_payload,
    save_runtime_config,
    save_runtime_config_to_path,
)
from graph.agent import AgentManager
from observability.tracing import is_langsmith_tracing_enabled

router = APIRouter(tags=["config"])

_BASE_DIR: Path | None = None
_AGENT_MANAGER: AgentManager | None = None


class RagModeRequest(BaseModel):
    enabled: bool


class RuntimeConfigRequest(BaseModel):
    config: dict[str, Any]


class TracingConfigRequest(BaseModel):
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
        raise ApiError(
            status_code=500,
            code="not_initialized",
            message="Config base directory is unavailable",
        )
    return _BASE_DIR


def _persist_env_flag(base_dir: Path, key: str, enabled: bool) -> None:
    env_path = base_dir / ".env"
    env_path.parent.mkdir(parents=True, exist_ok=True)
    value = "true" if enabled else "false"
    line = f"{key}={value}"
    text = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    pattern = re.compile(rf"(?m)^\\s*{re.escape(key)}\\s*=.*$")
    if pattern.search(text):
        updated = pattern.sub(line, text)
    elif text.strip():
        suffix = "" if text.endswith("\n") else "\n"
        updated = f"{text}{suffix}{line}\n"
    else:
        updated = f"{line}\n"
    env_path.write_text(updated, encoding="utf-8")


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
        raise ApiError(
            status_code=400, code="invalid_request", message=str(exc)
        ) from exc
    return {
        "data": {
            "enabled": runtime.runtime_config.rag_mode,
            "agent_id": runtime.agent_id,
        }
    }


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
        raise ApiError(
            status_code=400, code="invalid_request", message=str(exc)
        ) from exc
    return {
        "data": {
            "enabled": refreshed.runtime_config.rag_mode,
            "agent_id": refreshed.agent_id,
        }
    }


@router.get("/config/runtime")
async def get_runtime_config(
    agent_id: str = Query(default="default", min_length=1, max_length=64),
) -> dict[str, Any]:
    base_dir = _require_base_dir()
    if _AGENT_MANAGER is None:
        config = load_config(base_dir)
        return {
            "data": {
                "agent_id": "default",
                "config": runtime_to_payload(config.runtime),
            }
        }
    try:
        runtime = _AGENT_MANAGER.get_runtime(agent_id)
    except ValueError as exc:
        raise ApiError(
            status_code=400, code="invalid_request", message=str(exc)
        ) from exc
    return {
        "data": {
            "agent_id": runtime.agent_id,
            "config": runtime_to_payload(runtime.runtime_config),
        }
    }


@router.put("/config/runtime")
async def set_runtime_config(
    request: RuntimeConfigRequest,
    agent_id: str = Query(default="default", min_length=1, max_length=64),
) -> dict[str, Any]:
    base_dir = _require_base_dir()
    try:
        parsed_runtime = runtime_from_payload(request.config)
    except Exception as exc:  # noqa: BLE001
        raise ApiError(
            status_code=422,
            code="validation_error",
            message="Invalid runtime config payload",
        ) from exc

    if _AGENT_MANAGER is None:
        save_runtime_config(base_dir, parsed_runtime)
        return {
            "data": {
                "agent_id": "default",
                "config": runtime_to_payload(parsed_runtime),
            }
        }

    try:
        config_path = _AGENT_MANAGER.get_agent_config_path(agent_id)
        save_runtime_config_to_path(config_path, parsed_runtime)
        refreshed = _AGENT_MANAGER.get_runtime(agent_id)
    except ValueError as exc:
        raise ApiError(
            status_code=400, code="invalid_request", message=str(exc)
        ) from exc
    return {
        "data": {
            "agent_id": refreshed.agent_id,
            "config": runtime_to_payload(refreshed.runtime_config),
        }
    }


@router.get("/config/tracing")
async def get_tracing_config() -> dict[str, Any]:
    return {
        "data": {
            "provider": "langsmith",
            "config_key": "OBS_TRACING_ENABLED",
            "enabled": bool(is_langsmith_tracing_enabled()),
        }
    }


@router.put("/config/tracing")
async def set_tracing_config(request: TracingConfigRequest) -> dict[str, Any]:
    base_dir = _require_base_dir()
    enabled = bool(request.enabled)
    os.environ["OBS_TRACING_ENABLED"] = "true" if enabled else "false"
    _persist_env_flag(base_dir, "OBS_TRACING_ENABLED", enabled)
    return {
        "data": {
            "provider": "langsmith",
            "config_key": "OBS_TRACING_ENABLED",
            "enabled": bool(is_langsmith_tracing_enabled()),
        }
    }
