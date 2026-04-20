"""FastAPI router for hook management and audit visibility."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel

from api.errors import ApiError
from graph.agent import AgentManager
from hooks.engine import HookEngine
from hooks.types import HookConfig, HookEvent

router = APIRouter(prefix="/hooks", tags=["hooks"])

_agent_manager: AgentManager | None = None


def set_agent_manager(agent_manager: AgentManager) -> None:
    global _agent_manager
    _agent_manager = agent_manager


def _require_agent_manager() -> AgentManager:
    if _agent_manager is None:
        raise ApiError(
            status_code=500,
            code="not_initialized",
            message="Agent manager not initialized",
        )
    return _agent_manager


def _get_engine(agent_id: str) -> HookEngine:
    manager = _require_agent_manager()
    try:
        return manager.get_hook_engine(agent_id)
    except ValueError as exc:
        raise ApiError(
            status_code=400,
            code="invalid_request",
            message=str(exc),
        ) from exc


def _read_jsonl(path: Path, limit: int) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in reversed(path.read_text(encoding="utf-8").splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
        if len(rows) >= limit:
            break
    return rows


class HookCreateRequest(BaseModel):
    id: str
    type: str
    handler: str
    mode: str = "sync"
    timeout_ms: int = 10000


class HookResponse(BaseModel):
    id: str
    type: str
    handler: str
    mode: str
    timeout_ms: int


class HookAuditRow(BaseModel):
    timestamp_ms: int
    session_id: str
    run_id: str
    event: str
    hook_type: str
    status: str
    details: dict[str, Any]


def _row_agent_id(row: dict[str, Any]) -> str:
    details = row.get("details")
    if isinstance(details, dict):
        nested = str(details.get("agent_id", "")).strip()
        if nested:
            return nested
    return str(row.get("agent_id", "")).strip()


def _normalize_hook_audit_row(row: dict[str, Any]) -> HookAuditRow | None:
    event = str(row.get("event", "")).strip()
    if not event.startswith("hook_"):
        return None
    details = row.get("details")
    normalized_details = dict(details) if isinstance(details, dict) else {}
    hook_type = str(row.get("hook_type", "")).strip() or str(normalized_details.get("hook_type", "")).strip()
    status = str(row.get("status", "")).strip() or str(normalized_details.get("status", "")).strip()
    return HookAuditRow(
        timestamp_ms=int(row.get("timestamp_ms", 0) or 0),
        session_id=str(row.get("session_id", "")).strip(),
        run_id=str(row.get("run_id", "")).strip(),
        event=event,
        hook_type=hook_type,
        status=status,
        details=normalized_details,
    )


@router.get("")
async def list_hooks(
    agent_id: str = Query(..., min_length=1, max_length=128),
) -> list[HookResponse]:
    engine = _get_engine(agent_id)
    hooks = engine.list_hooks()
    return [
        HookResponse(
            id=hook.id,
            type=hook.type.value,
            handler=hook.handler,
            mode=hook.mode,
            timeout_ms=hook.timeout_ms,
        )
        for hook in hooks
    ]


@router.get("/audit")
async def list_hook_audit(
    agent_id: str = Query(..., min_length=1, max_length=128),
    limit: int = Query(default=50, ge=1, le=500),
) -> dict[str, Any]:
    manager = _require_agent_manager()
    try:
        runtime = manager.get_runtime(agent_id)
    except ValueError as exc:
        raise ApiError(
            status_code=400,
            code="invalid_request",
            message=str(exc),
        ) from exc
    rows = _read_jsonl(runtime.audit_store.steps_file, limit=limit * 8)
    normalized_rows: list[HookAuditRow] = []
    for row in rows:
        if _row_agent_id(row) != agent_id:
            continue
        normalized = _normalize_hook_audit_row(row)
        if normalized is None:
            continue
        normalized_rows.append(normalized)
        if len(normalized_rows) >= limit:
            break
    return {"rows": [row.model_dump() for row in normalized_rows]}


@router.post("")
async def add_hook(
    req: HookCreateRequest,
    agent_id: str = Query(..., min_length=1, max_length=128),
) -> HookResponse:
    engine = _get_engine(agent_id)
    try:
        config = HookConfig.from_dict(req.model_dump())
        engine.add_hook(config)
    except FileNotFoundError as exc:
        raise ApiError(
            status_code=400,
            code="invalid_request",
            message=str(exc),
        ) from exc
    except Exception as exc:
        raise ApiError(
            status_code=400,
            code="invalid_request",
            message=str(exc),
        ) from exc
    return HookResponse(
        id=config.id,
        type=config.type.value,
        handler=config.handler,
        mode=config.mode,
        timeout_ms=config.timeout_ms,
    )


@router.delete("/{hook_id}")
async def remove_hook(
    hook_id: str,
    agent_id: str = Query(..., min_length=1, max_length=128),
) -> dict[str, Any]:
    engine = _get_engine(agent_id)
    if not engine.remove_hook(hook_id):
        raise ApiError(
            status_code=404,
            code="not_found",
            message=f"Hook '{hook_id}' not found",
        )
    return {"deleted": hook_id}


@router.post("/{hook_id}/test")
async def test_hook(
    hook_id: str,
    agent_id: str = Query(..., min_length=1, max_length=128),
) -> dict[str, Any]:
    engine = _get_engine(agent_id)
    hook = next((item for item in engine.list_hooks() if item.id == hook_id), None)
    if hook is None:
        raise ApiError(
            status_code=404,
            code="not_found",
            message=f"Hook '{hook_id}' not found",
        )

    event = HookEvent(
        hook_type=hook.type.value,
        agent_id=agent_id,
        payload={"test": True},
    )
    result = engine.dispatch_sync(event)
    return {"hook_id": hook_id, "allow": result.allow, "reason": result.reason}
