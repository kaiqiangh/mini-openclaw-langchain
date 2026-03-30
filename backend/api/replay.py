"""Run replay API."""
from __future__ import annotations

import json
import time
import uuid
from typing import Any

from fastapi import APIRouter

from api.errors import ApiError
from graph.agent import AgentManager

router = APIRouter(tags=["replay"])

_agent_manager: AgentManager | None = None


def set_agent_manager(agent_manager: AgentManager) -> None:
    global _agent_manager
    _agent_manager = agent_manager


def _require_agent_manager() -> AgentManager:
    if _agent_manager is None:
        raise ApiError(status_code=500, code="not_initialized", message="Agent manager not initialized")
    return _agent_manager


@router.get("/agents/{agent_id}/runs/{run_id}")
async def get_run_details(agent_id: str, run_id: str) -> dict[str, Any]:
    """Get details of a specific run including tool calls."""
    manager = _require_agent_manager()
    try:
        runtime = manager.get_runtime(agent_id)
    except ValueError as exc:
        raise ApiError(status_code=400, code="invalid_request", message=str(exc)) from exc

    run = runtime.audit_store.get_run(run_id)
    if run is None:
        raise ApiError(status_code=404, code="not_found", message=f"Run not found: {run_id}")

    tool_calls_file = runtime.root_dir / "storage" / "audit" / "tool_calls.jsonl"
    tool_calls: list[dict[str, Any]] = []
    if tool_calls_file.exists():
        for line in tool_calls_file.read_text(encoding="utf-8").splitlines():
            try:
                data = json.loads(line)
                if data.get("run_id") == run_id:
                    tool_calls.append(data)
            except json.JSONDecodeError:
                continue

    return {"data": {"run": run, "tool_calls": tool_calls}}


@router.post("/agents/{agent_id}/runs/{run_id}/replay")
async def replay_run(agent_id: str, run_id: str) -> dict[str, Any]:
    """Re-execute a past run and return the new output."""
    manager = _require_agent_manager()
    try:
        runtime = manager.get_runtime(agent_id)
    except ValueError as exc:
        raise ApiError(status_code=400, code="invalid_request", message=str(exc)) from exc

    original_run = runtime.audit_store.get_run(run_id)
    if original_run is None:
        raise ApiError(status_code=404, code="not_found", message=f"Run not found: {run_id}")

    session_id = original_run.get("session_id", "")
    if not session_id:
        raise ApiError(status_code=400, code="invalid_state", message="Original run has no session_id")

    repository = manager.get_session_repository(agent_id)
    try:
        snapshot = await repository.load_snapshot(agent_id=agent_id, session_id=session_id)
    except FileNotFoundError as exc:
        raise ApiError(status_code=404, code="not_found", message=str(exc)) from exc

    user_messages = [m for m in snapshot.messages if m.get("role") == "user"]
    if not user_messages:
        raise ApiError(status_code=400, code="invalid_state", message="No user messages in session")

    original_message = str(user_messages[-1].get("content", ""))

    replay_session_id = f"replay:{run_id}:{uuid.uuid4().hex[:8]}"
    await runtime.session_manager.create_session(replay_session_id, title=f"Replay of {run_id}")

    try:
        result = await manager.run_once(
            message=original_message,
            session_id=replay_session_id,
            output_format="text",
            trigger_type="chat",
            agent_id=agent_id,
        )
    except Exception as exc:
        raise ApiError(
            status_code=500,
            code="replay_failed",
            message=f"Replay execution failed: {exc}",
        ) from exc

    return {
        "data": {
            "original_run_id": run_id,
            "replay_run_id": result.get("run_id", ""),
            "replay_session_id": replay_session_id,
            "session_id": session_id,
            "agent_id": agent_id,
            "original_message": original_message,
            "replay_output": result.get("text", ""),
            "replay_usage": result.get("usage", {}),
            "replayed_at": time.time(),
        }
    }
