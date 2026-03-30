"""Approval API for high-risk tool execution."""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from api.errors import ApiError
from storage.approval_store import ApprovalStatus, ApprovalStore

router = APIRouter(tags=["approval"])

_approval_store: ApprovalStore | None = None
_pending_waiters: dict[str, asyncio.Event] = {}
_pending_results: dict[str, ApprovalStatus] = {}


class ApprovalDecision(BaseModel):
    action: str = Field(pattern="^(approve|deny)$")
    reason: str | None = Field(default=None, max_length=500)


def set_dependencies(approval_store: ApprovalStore) -> None:
    global _approval_store
    _approval_store = approval_store


def _require_store() -> ApprovalStore:
    if _approval_store is None:
        raise ApiError(
            status_code=500,
            code="not_initialized",
            message="Approval store not initialized",
        )
    return _approval_store


@router.get("/agents/{agent_id}/approvals")
async def list_pending_approvals(
    agent_id: str,
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    store = _require_store()
    pending = store.list_pending(agent_id, limit=limit)
    return {
        "data": [
            {
                "request_id": r.request_id,
                "tool_name": r.tool_name,
                "tool_args": r.tool_args,
                "session_id": r.session_id,
                "run_id": r.run_id,
                "trigger_type": r.trigger_type,
                "created_at": r.created_at,
            }
            for r in pending
        ]
    }


@router.post("/agents/{agent_id}/approvals/{request_id}")
async def resolve_approval(
    agent_id: str,
    request_id: str,
    decision: ApprovalDecision,
) -> dict[str, Any]:
    store = _require_store()
    existing = store.get_request(agent_id, request_id)
    if existing is None:
        raise ApiError(
            status_code=404,
            code="not_found",
            message=f"Approval request not found: {request_id}",
        )
    if existing.status != ApprovalStatus.PENDING:
        raise ApiError(
            status_code=409,
            code="already_resolved",
            message=f"Approval request already resolved: {existing.status.value}",
        )

    new_status = ApprovalStatus.APPROVED if decision.action == "approve" else ApprovalStatus.DENIED
    store.resolve_request(
        agent_id,
        request_id,
        new_status,
        reason=decision.reason,
    )

    if request_id in _pending_waiters:
        _pending_results[request_id] = new_status
        _pending_waiters[request_id].set()

    return {
        "data": {
            "request_id": request_id,
            "status": new_status.value,
        }
    }


async def wait_for_approval(request_id: str, timeout_seconds: int = 300) -> ApprovalStatus:
    """Wait for an approval decision. Called by the tool runner."""
    event = asyncio.Event()
    _pending_waiters[request_id] = event
    try:
        await asyncio.wait_for(event.wait(), timeout=timeout_seconds)
        return _pending_results.pop(request_id, ApprovalStatus.DENIED)
    except asyncio.TimeoutError:
        return ApprovalStatus.EXPIRED
    finally:
        _pending_waiters.pop(request_id, None)
        _pending_results.pop(request_id, None)
