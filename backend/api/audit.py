"""Audit browsing API."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query

from api.agent_guard import require_existing_runtime
from api.errors import ApiError
from graph.agent import AgentManager
from utils.async_io import iter_jsonl_reversed

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
    results: list[dict[str, Any]] = []
    for row in iter_jsonl_reversed(path):
        results.append(row)
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
    runtime = require_existing_runtime(manager, agent_id)

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
    runtime = require_existing_runtime(manager, agent_id)

    audit_file = runtime.root_dir / "storage" / "audit" / "runs.jsonl"
    entries = _read_jsonl(audit_file, limit=limit)
    return {"data": entries}
