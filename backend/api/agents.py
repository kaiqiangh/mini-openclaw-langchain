from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Query, Response, status
from pydantic import BaseModel, Field

from api.errors import ApiError
from config import (
    runtime_from_payload,
    runtime_to_payload,
    save_runtime_config_to_path,
)
from graph.agent import AgentManager
from tools import build_tool_catalog, get_all_declared_tools

router = APIRouter(tags=["agents"])

_agent_manager: AgentManager | None = None
_TEMPLATE_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")


class CreateAgentRequest(BaseModel):
    agent_id: str = Field(min_length=1, max_length=64)


class AgentIdsRequest(BaseModel):
    agent_ids: list[str] = Field(min_length=1, max_length=200)


class BulkExportRequest(AgentIdsRequest):
    format: str = Field(default="json", max_length=20)


class BulkRuntimePatchRequest(AgentIdsRequest):
    patch: dict[str, Any]
    mode: str = Field(default="merge", max_length=20)


class AgentToolSelectionRequest(BaseModel):
    trigger: Literal["chat", "heartbeat", "cron"]
    enabled_tools: list[str] = Field(default_factory=list, max_length=200)


def set_agent_manager(agent_manager: AgentManager) -> None:
    global _agent_manager
    _agent_manager = agent_manager


def _require_agent_manager() -> AgentManager:
    if _agent_manager is None:
        raise ApiError(
            status_code=500,
            code="not_initialized",
            message="Agent manager is not initialized",
        )
    return _agent_manager


def _normalize_agent_id(value: str) -> str:
    return value.strip()


def _normalize_tool_names(values: list[str]) -> list[str]:
    normalized: list[str] = []
    for item in values:
        name = str(item).strip()
        if not name or name in normalized:
            continue
        normalized.append(name)
    return normalized


def _existing_agents(manager: AgentManager) -> dict[str, dict[str, Any]]:
    rows = manager.list_agents()
    return {
        str(item.get("agent_id", "")).strip(): item
        for item in rows
        if str(item.get("agent_id", "")).strip()
    }


def _base_dir(manager: AgentManager) -> Path:
    base_dir = getattr(manager, "base_dir", None)
    if not isinstance(base_dir, Path):
        raise ApiError(
            status_code=500,
            code="invalid_state",
            message="Agent base directory is unavailable",
        )
    return base_dir


def _templates_dir(manager: AgentManager) -> Path:
    path = _base_dir(manager) / "agent_templates"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _require_known_runtime(manager: AgentManager, agent_id: str):
    normalized = _normalize_agent_id(agent_id)
    known = _existing_agents(manager)
    if normalized not in known:
        raise ApiError(status_code=404, code="not_found", message="Agent not found")
    try:
        return manager.get_runtime(normalized)
    except ValueError as exc:
        raise ApiError(
            status_code=400, code="invalid_request", message=str(exc)
        ) from exc


def _agent_tools_payload(manager: AgentManager, agent_id: str) -> dict[str, Any]:
    runtime = _require_known_runtime(manager, agent_id)
    catalog = build_tool_catalog(
        runtime.root_dir,
        runtime.runtime_config,
        config_base_dir=_base_dir(manager),
    )
    return {"agent_id": runtime.agent_id, **catalog}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = _deep_merge(current, value)
        else:
            merged[key] = value
    return merged


def _flatten_diff(
    *,
    current: dict[str, Any],
    baseline: dict[str, Any],
    prefix: str = "",
) -> tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]]:
    added: dict[str, Any] = {}
    removed: dict[str, Any] = {}
    changed: dict[str, dict[str, Any]] = {}
    keys = set(current.keys()) | set(baseline.keys())
    for key in sorted(keys):
        path = f"{prefix}.{key}" if prefix else str(key)
        in_current = key in current
        in_baseline = key in baseline
        if in_current and not in_baseline:
            added[path] = current[key]
            continue
        if in_baseline and not in_current:
            removed[path] = baseline[key]
            continue
        current_value = current[key]
        baseline_value = baseline[key]
        if isinstance(current_value, dict) and isinstance(baseline_value, dict):
            nested_added, nested_removed, nested_changed = _flatten_diff(
                current=current_value, baseline=baseline_value, prefix=path
            )
            added.update(nested_added)
            removed.update(nested_removed)
            changed.update(nested_changed)
            continue
        if current_value != baseline_value:
            changed[path] = {"from": baseline_value, "to": current_value}
    return added, removed, changed


def _template_path(manager: AgentManager, template_name: str) -> Path:
    name = template_name.strip()
    if not _TEMPLATE_NAME_PATTERN.match(name):
        raise ApiError(
            status_code=400,
            code="invalid_request",
            message="Invalid template name",
        )
    path = _templates_dir(manager) / f"{name}.json"
    if not path.exists() or not path.is_file():
        raise ApiError(
            status_code=404,
            code="not_found",
            message="Template not found",
        )
    return path


def _load_template(manager: AgentManager, template_name: str) -> dict[str, Any]:
    path = _template_path(manager, template_name)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ApiError(
            status_code=500,
            code="invalid_state",
            message=f"Template {template_name} is not valid JSON",
        ) from exc
    if not isinstance(payload, dict):
        raise ApiError(
            status_code=500,
            code="invalid_state",
            message=f"Template {template_name} has invalid payload shape",
        )
    runtime_payload = payload.get("runtime_config", payload)
    if not isinstance(runtime_payload, dict):
        raise ApiError(
            status_code=500,
            code="invalid_state",
            message=f"Template {template_name} runtime config must be an object",
        )
    try:
        normalized = runtime_to_payload(runtime_from_payload(runtime_payload))
    except Exception as exc:
        raise ApiError(
            status_code=500,
            code="invalid_state",
            message=f"Template {template_name} runtime config is invalid",
        ) from exc
    return {
        "name": template_name,
        "description": str(payload.get("description", "")).strip(),
        "path": str(path),
        "updated_at": float(path.stat().st_mtime),
        "runtime_config": normalized,
    }


@router.get("/agents")
async def list_agents() -> dict[str, Any]:
    manager = _require_agent_manager()
    return {"data": manager.list_agents()}


@router.post("/agents", status_code=status.HTTP_201_CREATED)
async def create_agent(req: CreateAgentRequest, response: Response) -> dict[str, Any]:
    manager = _require_agent_manager()
    try:
        created = manager.create_agent(req.agent_id)
    except ValueError as exc:
        raise ApiError(
            status_code=400, code="invalid_request", message=str(exc)
        ) from exc
    response.headers["Location"] = f"/api/v1/agents/{req.agent_id}"
    return {"data": created}


@router.delete("/agents/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(agent_id: str) -> Response:
    manager = _require_agent_manager()
    try:
        deleted = manager.delete_agent(agent_id)
    except ValueError as exc:
        raise ApiError(
            status_code=400, code="invalid_request", message=str(exc)
        ) from exc
    if not deleted:
        raise ApiError(status_code=404, code="not_found", message="Agent not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/agents/bulk-delete")
async def bulk_delete_agents(request: AgentIdsRequest) -> dict[str, Any]:
    manager = _require_agent_manager()
    results: list[dict[str, Any]] = []
    deleted_count = 0
    for raw in request.agent_ids:
        agent_id = _normalize_agent_id(raw)
        if not agent_id:
            results.append(
                {"agent_id": raw, "deleted": False, "error": "invalid_agent_id"}
            )
            continue
        try:
            deleted = manager.delete_agent(agent_id)
        except ValueError as exc:
            results.append(
                {"agent_id": agent_id, "deleted": False, "error": str(exc)}
            )
            continue
        if not deleted:
            results.append({"agent_id": agent_id, "deleted": False, "error": "not_found"})
            continue
        deleted_count += 1
        results.append({"agent_id": agent_id, "deleted": True})
    return {
        "data": {
            "requested_count": len(request.agent_ids),
            "deleted_count": deleted_count,
            "results": results,
        }
    }


@router.post("/agents/bulk-export")
async def bulk_export_agents(request: BulkExportRequest) -> dict[str, Any]:
    manager = _require_agent_manager()
    export_format = request.format.strip().lower() or "json"
    if export_format != "json":
        raise ApiError(
            status_code=422,
            code="validation_error",
            message="Only json export format is supported",
        )

    known = _existing_agents(manager)
    exported: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for raw in request.agent_ids:
        agent_id = _normalize_agent_id(raw)
        if not agent_id:
            errors.append({"agent_id": raw, "error": "invalid_agent_id"})
            continue
        metadata = known.get(agent_id)
        if metadata is None:
            errors.append({"agent_id": agent_id, "error": "not_found"})
            continue
        runtime = manager.get_runtime(agent_id)
        exported.append(
            {
                "agent_id": agent_id,
                "metadata": metadata,
                "runtime_config": runtime_to_payload(runtime.runtime_config),
            }
        )
    return {
        "data": {
            "format": "json",
            "generated_at_ms": int(time.time() * 1000),
            "agents": exported,
            "errors": errors,
        }
    }


@router.post("/agents/bulk-runtime-patch")
async def bulk_runtime_patch(request: BulkRuntimePatchRequest) -> dict[str, Any]:
    manager = _require_agent_manager()
    mode = request.mode.strip().lower() or "merge"
    if mode not in {"merge", "replace"}:
        raise ApiError(
            status_code=422,
            code="validation_error",
            message="mode must be one of: merge, replace",
        )

    known = _existing_agents(manager)
    updated_count = 0
    results: list[dict[str, Any]] = []
    for raw in request.agent_ids:
        agent_id = _normalize_agent_id(raw)
        if not agent_id:
            results.append(
                {"agent_id": raw, "updated": False, "error": "invalid_agent_id"}
            )
            continue
        if agent_id not in known:
            results.append({"agent_id": agent_id, "updated": False, "error": "not_found"})
            continue
        try:
            current_runtime = manager.get_runtime(agent_id)
            current_payload = runtime_to_payload(current_runtime.runtime_config)
            next_payload = (
                _deep_merge(current_payload, request.patch)
                if mode == "merge"
                else request.patch
            )
            parsed = runtime_from_payload(next_payload)
            config_path = manager.get_agent_config_path(agent_id)
            save_runtime_config_to_path(config_path, parsed)
            refreshed = manager.get_runtime(agent_id)
            updated_count += 1
            results.append(
                {
                    "agent_id": agent_id,
                    "updated": True,
                    "config": runtime_to_payload(refreshed.runtime_config),
                }
            )
        except Exception as exc:  # noqa: BLE001
            results.append({"agent_id": agent_id, "updated": False, "error": str(exc)})
    return {
        "data": {
            "requested_count": len(request.agent_ids),
            "updated_count": updated_count,
            "results": results,
        }
    }


@router.get("/agents/templates")
async def list_agent_templates() -> dict[str, Any]:
    manager = _require_agent_manager()
    template_dir = _templates_dir(manager)
    templates: list[dict[str, Any]] = []
    for path in sorted(template_dir.glob("*.json"), key=lambda item: item.name):
        name = path.stem
        try:
            loaded = _load_template(manager, name)
        except ApiError:
            continue
        templates.append(
            {
                "name": loaded["name"],
                "description": loaded["description"],
                "path": loaded["path"],
                "updated_at": loaded["updated_at"],
            }
        )
    return {"data": templates}


@router.get("/agents/templates/{template_name}")
async def get_agent_template(template_name: str) -> dict[str, Any]:
    manager = _require_agent_manager()
    loaded = _load_template(manager, template_name)
    return {"data": loaded}


@router.get("/agents/{agent_id}/runtime-diff")
async def get_agent_runtime_diff(
    agent_id: str, baseline: str = Query(default="default", max_length=128)
) -> dict[str, Any]:
    manager = _require_agent_manager()
    known = _existing_agents(manager)
    if agent_id not in known:
        raise ApiError(status_code=404, code="not_found", message="Agent not found")

    candidate_payload = runtime_to_payload(manager.get_runtime(agent_id).runtime_config)
    normalized_baseline = baseline.strip() or "default"
    baseline_payload: dict[str, Any]

    if normalized_baseline == "default":
        baseline_payload = runtime_to_payload(manager.get_runtime("default").runtime_config)
    elif normalized_baseline.startswith("agent:"):
        other_agent = normalized_baseline.split(":", 1)[1].strip()
        if not other_agent or other_agent not in known:
            raise ApiError(
                status_code=404,
                code="not_found",
                message="Baseline agent not found",
            )
        baseline_payload = runtime_to_payload(manager.get_runtime(other_agent).runtime_config)
    elif normalized_baseline.startswith("template:"):
        template_name = normalized_baseline.split(":", 1)[1].strip()
        if not template_name:
            raise ApiError(
                status_code=400,
                code="invalid_request",
                message="Template baseline is invalid",
            )
        baseline_payload = _load_template(manager, template_name)["runtime_config"]
    else:
        raise ApiError(
            status_code=400,
            code="invalid_request",
            message="Unsupported baseline. Use default, agent:<id>, or template:<name>",
        )

    added, removed, changed = _flatten_diff(
        current=candidate_payload, baseline=baseline_payload
    )
    return {
        "data": {
            "agent_id": agent_id,
            "baseline": normalized_baseline,
            "summary": {
                "added": len(added),
                "removed": len(removed),
                "changed": len(changed),
                "total": len(added) + len(removed) + len(changed),
            },
            "added": added,
            "removed": removed,
            "changed": changed,
        }
    }


@router.get("/agents/{agent_id}/tools")
async def get_agent_tools(agent_id: str) -> dict[str, Any]:
    manager = _require_agent_manager()
    return {"data": _agent_tools_payload(manager, agent_id)}


@router.put("/agents/{agent_id}/tools/selection")
async def update_agent_tool_selection(
    agent_id: str, request: AgentToolSelectionRequest
) -> dict[str, Any]:
    manager = _require_agent_manager()
    runtime = _require_known_runtime(manager, agent_id)

    normalized_enabled = _normalize_tool_names(request.enabled_tools)
    declared = get_all_declared_tools(
        runtime.root_dir,
        runtime.runtime_config,
        config_base_dir=_base_dir(manager),
    )
    declared_names = {tool.name for tool in declared}
    unknown_tools = sorted(
        tool_name for tool_name in normalized_enabled if tool_name not in declared_names
    )
    if unknown_tools:
        raise ApiError(
            status_code=422,
            code="validation_error",
            message="Unknown tool names in enabled_tools",
            details={"unknown_tools": unknown_tools},
        )

    if request.trigger == "chat":
        runtime.runtime_config.chat_enabled_tools = normalized_enabled
    elif request.trigger == "heartbeat":
        runtime.runtime_config.autonomous_tools.heartbeat_enabled_tools = (
            normalized_enabled
        )
    else:
        runtime.runtime_config.autonomous_tools.cron_enabled_tools = normalized_enabled

    config_path = manager.get_agent_config_path(runtime.agent_id)
    save_runtime_config_to_path(config_path, runtime.runtime_config)
    return {"data": _agent_tools_payload(manager, runtime.agent_id)}
