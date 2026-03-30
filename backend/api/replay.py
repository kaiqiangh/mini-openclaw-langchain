"""Run replay API."""
from __future__ import annotations

import difflib
import json
import time
import uuid
from typing import Any

from fastapi import APIRouter, Query

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


def _compute_line_diff(text_a: str, text_b: str) -> list[dict[str, Any]]:
    """Compute unified line diff between two texts."""
    lines_a = text_a.splitlines(keepends=True)
    lines_b = text_b.splitlines(keepends=True)
    diff = list(difflib.unified_diff(lines_a, lines_b, fromfile="run_a", tofile="run_b", lineterm=""))
    hunks: list[dict[str, Any]] = []
    current_hunk: dict[str, Any] | None = None
    for line in diff:
        if line.startswith("@@"):
            if current_hunk:
                hunks.append(current_hunk)
            current_hunk = {"header": line.strip(), "lines": []}
        elif current_hunk is not None:
            current_hunk["lines"].append(line.rstrip("\n"))
    if current_hunk:
        hunks.append(current_hunk)
    return hunks


@router.get("/agents/{agent_id}/runs/compare")
async def compare_runs(
    agent_id: str,
    run_a: str = Query(..., min_length=1, max_length=128),
    run_b: str = Query(..., min_length=1, max_length=128),
) -> dict[str, Any]:
    """Compare outputs of two runs side-by-side."""
    manager = _require_agent_manager()
    try:
        runtime = manager.get_runtime(agent_id)
    except ValueError as exc:
        raise ApiError(status_code=400, code="invalid_request", message=str(exc)) from exc

    data_a = runtime.audit_store.get_run(run_a)
    data_b = runtime.audit_store.get_run(run_b)
    if data_a is None:
        raise ApiError(status_code=404, code="not_found", message=f"Run not found: {run_a}")
    if data_b is None:
        raise ApiError(status_code=404, code="not_found", message=f"Run not found: {run_b}")

    # Load tool calls for both runs
    tool_calls_file = runtime.root_dir / "storage" / "audit" / "tool_calls.jsonl"
    tool_calls_a: list[dict[str, Any]] = []
    tool_calls_b: list[dict[str, Any]] = []
    if tool_calls_file.exists():
        for line in tool_calls_file.read_text(encoding="utf-8").splitlines():
            try:
                data = json.loads(line)
                rid = data.get("run_id", "")
                if rid == run_a:
                    tool_calls_a.append(data)
                elif rid == run_b:
                    tool_calls_b.append(data)
            except json.JSONDecodeError:
                continue

    # Extract assistant outputs from session histories
    repository = manager.get_session_repository(agent_id)
    output_a = ""
    output_b = ""

    session_id_a = data_a.get("session_id", "")
    session_id_b = data_b.get("session_id", "")

    if session_id_a:
        try:
            snapshot_a = await repository.load_snapshot(agent_id=agent_id, session_id=session_id_a)
            assistant_msgs_a = [m for m in snapshot_a.messages if m.get("role") == "assistant"]
            if assistant_msgs_a:
                output_a = str(assistant_msgs_a[-1].get("content", ""))
        except FileNotFoundError:
            pass

    if session_id_b:
        try:
            snapshot_b = await repository.load_snapshot(agent_id=agent_id, session_id=session_id_b)
            assistant_msgs_b = [m for m in snapshot_b.messages if m.get("role") == "assistant"]
            if assistant_msgs_b:
                output_b = str(assistant_msgs_b[-1].get("content", ""))
        except FileNotFoundError:
            pass

    diff_hunks = _compute_line_diff(output_a, output_b)

    return {
        "data": {
            "run_a": {"run_id": run_a, "session_id": session_id_a, "output": output_a, "tool_calls": tool_calls_a},
            "run_b": {"run_id": run_b, "session_id": session_id_b, "output": output_b, "tool_calls": tool_calls_b},
            "diff": {
                "hunks": diff_hunks,
                "total_additions": sum(1 for h in diff_hunks for l in h["lines"] if l.startswith("+") and not l.startswith("+++")),
                "total_deletions": sum(1 for h in diff_hunks for l in h["lines"] if l.startswith("-") and not l.startswith("---")),
            },
        }
    }


@router.get("/agents/{agent_id}/runs/replays")
async def list_replays(
    agent_id: str,
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    """List replay sessions and their source runs."""
    manager = _require_agent_manager()
    try:
        runtime = manager.get_runtime(agent_id)
    except ValueError as exc:
        raise ApiError(status_code=400, code="invalid_request", message=str(exc)) from exc

    session_manager = runtime.session_manager
    all_sessions = await session_manager.list_sessions()
    replay_sessions = [
        s for s in all_sessions
        if s.get("session_id", "").startswith("replay:")
    ]

    results: list[dict[str, Any]] = []
    for session in replay_sessions[:limit]:
        sid = session.get("session_id", "")
        parts = sid.split(":", 2)
        original_run_id = parts[1] if len(parts) >= 2 else ""
        results.append({
            "session_id": sid,
            "original_run_id": original_run_id,
            "title": session.get("title", ""),
            "created_at": session.get("created_at", 0),
            "updated_at": session.get("updated_at", 0),
        })

    return {"data": {"replays": results, "count": len(results)}}
