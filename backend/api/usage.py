from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from api.errors import ApiError
from graph.agent import AgentManager
from storage.usage_store import UsageQuery, UsageStore

router = APIRouter(tags=["usage"])

_agent_manager: AgentManager | None = None


def set_agent_manager(agent_manager: AgentManager) -> None:
    global _agent_manager
    _agent_manager = agent_manager


def _require_store(agent_id: str) -> UsageStore:
    if _agent_manager is None:
        raise ApiError(
            status_code=500,
            code="not_initialized",
            message="Usage store is not initialized",
        )
    try:
        return _agent_manager.get_usage_store(agent_id)
    except ValueError as exc:
        raise ApiError(
            status_code=400, code="invalid_request", message=str(exc)
        ) from exc


@router.get("/usage/records")
async def get_usage_records(
    since_hours: int = Query(default=24, ge=1, le=24 * 365),
    provider: str | None = None,
    model: str | None = None,
    trigger_type: str | None = None,
    session_id: str | None = None,
    limit: int = Query(default=200, ge=1, le=2000),
    agent_id: str = Query(default="default", min_length=1, max_length=64),
) -> dict[str, Any]:
    store = _require_store(agent_id)
    query = UsageQuery(
        since_hours=since_hours,
        provider=provider,
        model=model,
        trigger_type=trigger_type,
        session_id=session_id,
        limit=limit,
    )
    records = store.query_records(query)
    return {
        "data": {
            "filters": {
                "agent_id": agent_id,
                "since_hours": since_hours,
                "provider": provider or "",
                "model": model or "",
                "trigger_type": trigger_type or "",
                "session_id": session_id or "",
                "limit": limit,
            },
            "records": records,
            "count": len(records),
        }
    }


@router.get("/usage/summary")
async def get_usage_summary(
    since_hours: int = Query(default=24, ge=1, le=24 * 365),
    provider: str | None = None,
    model: str | None = None,
    trigger_type: str | None = None,
    session_id: str | None = None,
    agent_id: str = Query(default="default", min_length=1, max_length=64),
) -> dict[str, Any]:
    store = _require_store(agent_id)
    records = store.query_records(
        UsageQuery(
            since_hours=since_hours,
            provider=provider,
            model=model,
            trigger_type=trigger_type,
            session_id=session_id,
            limit=100000,
        )
    )
    summary = store.summarize(records)
    return {
        "data": {
            "filters": {
                "agent_id": agent_id,
                "since_hours": since_hours,
                "provider": provider or "",
                "model": model or "",
                "trigger_type": trigger_type or "",
                "session_id": session_id or "",
            },
            "totals": summary["totals"],
            "by_provider_model": summary["by_provider_model"],
            "by_provider": summary["by_provider"],
            "count": len(records),
        }
    }
