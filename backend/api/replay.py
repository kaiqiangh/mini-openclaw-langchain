"""Run replay API."""
from __future__ import annotations

import difflib
import time
import uuid
from typing import Any

from fastapi import APIRouter, Query

from api.agent_guard import require_existing_runtime
from api.errors import ApiError
from graph.agent import AgentManager
from graph.session_manager import InvalidSessionIdError
from storage.usage_store import UsageQuery
from utils.async_io import iter_jsonl_reversed

router = APIRouter(tags=["replay"])

_agent_manager: AgentManager | None = None


def set_agent_manager(agent_manager: AgentManager) -> None:
    global _agent_manager
    _agent_manager = agent_manager


def _require_agent_manager() -> AgentManager:
    if _agent_manager is None:
        raise ApiError(status_code=500, code="not_initialized", message="Agent manager not initialized")
    return _agent_manager


def _run_steps(runtime: Any, run_id: str) -> list[dict[str, Any]]:
    path = runtime.root_dir / "storage" / "audit" / "steps.jsonl"
    rows = [row for row in iter_jsonl_reversed(path) if row.get("run_id") == run_id]
    rows.reverse()
    return rows[:500]


def _run_evidence(runtime: Any, run_id: str) -> dict[str, Any]:
    steps = _run_steps(runtime, run_id)
    event_counts: dict[str, int] = {}
    retries: list[dict[str, Any]] = []
    fallbacks: list[dict[str, Any]] = []
    degradations: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    delegate_lifecycle: list[dict[str, Any]] = []
    for row in steps:
        event = str(row.get("event", "unknown"))
        event_counts[event] = event_counts.get(event, 0) + 1
        details = row.get("details") if isinstance(row.get("details"), dict) else {}
        if event == "llm_retry_attempt":
            retries.append(details)
        if event == "llm_fallback_attempt" or event == "llm_fallback_selected":
            fallbacks.append({"event": event, **details})
        if details.get("degradation") or "degrad" in event:
            degradations.append({"event": event, **details})
        if event in {"llm_error", "llm_route_exhausted", "error", "persistence_error"}:
            errors.append({"event": event, **details})
        if event.startswith("delegate") or details.get("delegate_id"):
            delegate_lifecycle.append({"event": event, **details})

    usage: list[dict[str, Any]] = []
    usage_store = getattr(runtime, "usage_store", None)
    if usage_store is not None:
        usage = usage_store.query_records(
            UsageQuery(since_hours=24 * 365, limit=200)
        )
        usage = [row for row in usage if row.get("run_id") == run_id][:20]
    return {
        "event_counts": event_counts,
        "retries": retries[:20],
        "fallbacks": fallbacks[:20],
        "degradations": degradations[:20],
        "errors": errors[:20],
        "delegate_lifecycle": delegate_lifecycle[:100],
        "usage": usage,
    }


@router.get("/agents/{agent_id}/runs/{run_id}")
async def get_run_details(agent_id: str, run_id: str) -> dict[str, Any]:
    """Get details of a specific run including tool calls."""
    manager = _require_agent_manager()
    runtime = require_existing_runtime(manager, agent_id)

    run = runtime.audit_store.get_run(run_id)
    if run is None:
        raise ApiError(status_code=404, code="not_found", message=f"Run not found: {run_id}")

    tool_calls_file = runtime.root_dir / "storage" / "audit" / "tool_calls.jsonl"
    tool_calls: list[dict[str, Any]] = []
    for data in iter_jsonl_reversed(tool_calls_file):
        if data.get("run_id") == run_id:
            tool_calls.append(data)
    tool_calls.reverse()

    return {
        "data": {
            "run": run,
            "tool_calls": tool_calls,
            "steps": _run_steps(runtime, run_id),
            "evidence": _run_evidence(runtime, run_id),
        }
    }


@router.post("/agents/{agent_id}/runs/{run_id}/replay")
async def replay_run(agent_id: str, run_id: str) -> dict[str, Any]:
    """Re-execute a past run and return the new output."""
    manager = _require_agent_manager()
    runtime = require_existing_runtime(manager, agent_id)

    original_run = runtime.audit_store.get_run(run_id)
    if original_run is None:
        raise ApiError(status_code=404, code="not_found", message=f"Run not found: {run_id}")

    session_id = original_run.get("session_id", "")
    if not session_id:
        raise ApiError(status_code=400, code="invalid_state", message="Original run has no session_id")

    repository = manager.get_session_repository(agent_id)
    try:
        snapshot = await repository.load_snapshot(agent_id=agent_id, session_id=session_id)
    except InvalidSessionIdError as exc:
        raise ApiError(status_code=400, code="invalid_state", message=str(exc)) from exc
    except FileNotFoundError as exc:
        raise ApiError(status_code=404, code="not_found", message=str(exc)) from exc

    user_messages = [m for m in snapshot.messages if m.get("role") == "user"]
    if not user_messages:
        raise ApiError(status_code=400, code="invalid_state", message="No user messages in session")

    run_details = original_run.get("details")
    run_details = run_details if isinstance(run_details, dict) else {}
    frozen_input = run_details.get("input_snapshot")
    if isinstance(frozen_input, dict):
        original_message = str(frozen_input.get("message", ""))
        replay_history = frozen_input.get("history", [])
        replay_history = replay_history if isinstance(replay_history, list) else []
    else:
        original_message = str(user_messages[-1].get("content", ""))
        replay_history = []

    replay_session_id = f"replay:{run_id}:{uuid.uuid4().hex[:8]}"
    try:
        await runtime.session_manager.create_session(
            replay_session_id, title=f"Replay of {run_id}"
        )
    except InvalidSessionIdError as exc:
        raise ApiError(status_code=400, code="invalid_request", message=str(exc)) from exc

    try:
        result = await manager.run_once(
            message=original_message,
            session_id=replay_session_id,
            history=[item for item in replay_history if isinstance(item, dict)],
            output_format="text",
            trigger_type="replay",
            agent_id=agent_id,
            explicit_enabled_tools=[],
            explicit_blocked_tools=[],
            replay_source_run_id=run_id,
        )
    except Exception as exc:
        raise ApiError(
            status_code=500,
            code="replay_failed",
            message=f"Replay execution failed: {exc}",
        ) from exc

    replay_run_id = result.get("run_id", "")
    replay_run = runtime.audit_store.get_run(replay_run_id) or {}
    replay_details = replay_run.get("details")
    replay_details = replay_details if isinstance(replay_details, dict) else {}
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
            "provenance": {
                "source_run_id": run_id,
                "replay_run_id": replay_run_id,
                "input_digest": run_details.get("input_digest", ""),
                "replay_input_digest": replay_details.get("input_digest", ""),
                "source_runtime_config_digest": run_details.get(
                    "runtime_config_digest", ""
                ),
                "replay_runtime_config_digest": replay_details.get(
                    "runtime_config_digest", ""
                ),
                "source_skill_catalog_digest": run_details.get(
                    "skill_catalog_digest", ""
                ),
                "replay_skill_catalog_digest": replay_details.get(
                    "skill_catalog_digest", ""
                ),
                "tools_disabled": True,
            },
            "evidence": _run_evidence(runtime, replay_run_id),
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
    runtime = require_existing_runtime(manager, agent_id)

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
    for data in iter_jsonl_reversed(tool_calls_file):
        rid = data.get("run_id", "")
        if rid == run_a:
            tool_calls_a.append(data)
        elif rid == run_b:
            tool_calls_b.append(data)
    tool_calls_a.reverse()
    tool_calls_b.reverse()

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

    evidence_a = _run_evidence(runtime, run_a)
    evidence_b = _run_evidence(runtime, run_b)
    return {
        "data": {
            "run_a": {
                "run_id": run_a,
                "session_id": session_id_a,
                "status": data_a.get("status", ""),
                "output": output_a,
                "tool_calls": tool_calls_a,
                "evidence": evidence_a,
            },
            "run_b": {
                "run_id": run_b,
                "session_id": session_id_b,
                "status": data_b.get("status", ""),
                "output": output_b,
                "tool_calls": tool_calls_b,
                "evidence": evidence_b,
            },
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
    runtime = require_existing_runtime(manager, agent_id)

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
