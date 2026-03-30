"""Audit browsing API."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query

from api.errors import ApiError
from graph.agent import AgentManager

router = APIRouter(tags=["audit"])

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


def _read_jsonl(path: Path, limit: int) -> list[dict[str, Any]]:
    """Read last N lines from a JSONL file, most recent first."""
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    results: list[dict[str, Any]] = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            results.append(json.loads(line))
        except json.JSONDecodeError:
            continue
        if len(results) >= limit:
            break
    return results


@router.get("/agents/{agent_id}/audit/tool-calls")
async def list_tool_calls(
    agent_id: str,
    limit: int = Query(default=50, ge=1, le=500),
    tool_name: str | None = Query(default=None, max_length=64),
    status: str | None = Query(default=None, max_length=20),
) -> dict[str, Any]:
    manager = _require_agent_manager()
    try:
        runtime = manager.get_runtime(agent_id)
    except ValueError as exc:
        raise ApiError(
            status_code=400, code="invalid_request", message=str(exc)
        ) from exc

    audit_file = runtime.root_dir / "storage" / "audit" / "tool_calls.jsonl"
    entries = _read_jsonl(audit_file, limit=limit)

    if tool_name:
        entries = [e for e in entries if e.get("tool_name") == tool_name]
    if status:
        entries = [e for e in entries if e.get("status") == status]

    return {"data": entries}


@router.get("/agents/{agent_id}/audit/runs")
async def list_runs(
    agent_id: str,
    limit: int = Query(default=50, ge=1, le=500),
) -> dict[str, Any]:
    manager = _require_agent_manager()
    try:
        runtime = manager.get_runtime(agent_id)
    except ValueError as exc:
        raise ApiError(
            status_code=400, code="invalid_request", message=str(exc)
        ) from exc

    audit_file = runtime.root_dir / "storage" / "audit" / "runs.jsonl"
    entries = _read_jsonl(audit_file, limit=limit)
    return {"data": entries}
