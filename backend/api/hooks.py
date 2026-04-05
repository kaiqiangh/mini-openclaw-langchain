"""FastAPI router for hook management."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from hooks.engine import HookEngine
from hooks.types import HookConfig, HookEvent, HookType

router = APIRouter(prefix="/api/v1/hooks", tags=["hooks"])

# ── Helpers ─────────────────────────────────────────────────────


def _get_engine(agent_id: str) -> HookEngine:
    """Get the HookEngine for an agent via dependency injection.

    This is overridden at app startup via the manager dependency.
    For now, we use a simple lookup pattern. If the agent manager
    is not available, the API returns 501 Not Implemented.
    """
    # This will be wired through app.py — for now return a sentinel
    # that the calling code checks.
    raise NotImplementedError(
        "HookEngine lookup requires AgentManager wiring. "
        "Use the agent_manager.get_hook_engine(agent_id) pattern."
    )


# ── Request Models ──────────────────────────────────────────────

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


# ── Endpoints ───────────────────────────────────────────────────

@router.get("/")
async def list_hooks(agent_id: str):
    """List all configured hooks for an agent."""
    try:
        engine = _get_engine(agent_id)
    except NotImplementedError:
        raise HTTPException(501, "HookEngine not wired yet")
    hooks = engine.list_hooks()
    return [
        HookResponse(
            id=h.id, type=h.type.value, handler=h.handler,
            mode=h.mode, timeout_ms=h.timeout_ms,
        )
        for h in hooks
    ]


@router.post("/")
async def add_hook(req: HookCreateRequest, agent_id: str):
    """Add a new hook configuration."""
    try:
        engine = _get_engine(agent_id)
    except NotImplementedError:
        raise HTTPException(501, "HookEngine not wired yet")
    try:
        config = HookConfig.from_dict(req.model_dump())
        engine.add_hook(config)
    except FileNotFoundError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(400, str(exc))
    return HookResponse(
        id=config.id, type=config.type.value, handler=config.handler,
        mode=config.mode, timeout_ms=config.timeout_ms,
    )


@router.delete("/{hook_id}")
async def remove_hook(hook_id: str, agent_id: str):
    """Remove a hook by id."""
    try:
        engine = _get_engine(agent_id)
    except NotImplementedError:
        raise HTTPException(501, "HookEngine not wired yet")
    if not engine.remove_hook(hook_id):
        raise HTTPException(404, f"Hook '{hook_id}' not found")
    return {"deleted": hook_id}


@router.post("/{hook_id}/test")
async def test_hook(hook_id: str, agent_id: str):
    """Dry-run a hook with a synthetic event."""
    try:
        engine = _get_engine(agent_id)
    except NotImplementedError:
        raise HTTPException(501, "HookEngine not wired yet")
    hooks = engine.list_hooks()
    hook = next((h for h in hooks if h.id == hook_id), None)
    if hook is None:
        raise HTTPException(404, f"Hook '{hook_id}' not found")

    event = HookEvent(hook_type=hook.type.value, agent_id=agent_id, payload={"test": True})
    result = engine.dispatch_sync(event)
    return {"hook_id": hook_id, "allow": result.allow, "reason": result.reason}
