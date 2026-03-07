from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import Any, Iterable

from fastapi import APIRouter, Query

from api.errors import ApiError
from graph.agent import AgentManager

router = APIRouter(tags=["traces"])

_agent_manager: AgentManager | None = None

WINDOW_TO_MS = {
    "1h": 60 * 60 * 1000,
    "4h": 4 * 60 * 60 * 1000,
    "12h": 12 * 60 * 60 * 1000,
    "24h": 24 * 60 * 60 * 1000,
    "7d": 7 * 24 * 60 * 60 * 1000,
    "30d": 30 * 24 * 60 * 60 * 1000,
}


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


def _require_agent_root(agent_id: str) -> Path:
    manager = _require_agent_manager()
    try:
        runtime = manager.get_runtime(agent_id)
    except ValueError as exc:
        raise ApiError(
            status_code=400,
            code="invalid_request",
            message=str(exc),
        ) from exc
    return runtime.root_dir


def _read_jsonl_rows(path: Path) -> Iterable[tuple[int, dict[str, Any]]]:
    if not path.exists() or not path.is_file():
        return []

    rows: list[tuple[int, dict[str, Any]]] = []
    with path.open("r", encoding="utf-8") as fh:
        for index, line in enumerate(fh, start=1):
            raw = line.strip()
            if not raw:
                continue
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                rows.append((index, parsed))
    return rows


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return text or ""


def _as_nullable_text(value: Any) -> str | None:
    text = _as_text(value)
    return text or None


def _as_int(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return parsed if parsed > 0 else 0


def _truncate(value: str, limit: int = 160) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 1]}…"


def _encode_cursor(timestamp_ms: int, event_id: str) -> str:
    payload = json.dumps(
        {"timestamp_ms": timestamp_ms, "event_id": event_id},
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii")


def _decode_cursor(cursor: str) -> tuple[int, str]:
    try:
        payload = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        parsed = json.loads(payload)
    except Exception as exc:
        raise ApiError(
            status_code=400,
            code="invalid_request",
            message="Invalid trace cursor",
        ) from exc

    if not isinstance(parsed, dict):
        raise ApiError(
            status_code=400,
            code="invalid_request",
            message="Invalid trace cursor",
        )

    timestamp_ms = _as_int(parsed.get("timestamp_ms"))
    event_id = _as_text(parsed.get("event_id"))
    if timestamp_ms <= 0 or not event_id:
        raise ApiError(
            status_code=400,
            code="invalid_request",
            message="Invalid trace cursor",
        )
    return timestamp_ms, event_id


def _normalize_audit_step(
    row: dict[str, Any],
    *,
    agent_id: str,
    line_number: int,
) -> dict[str, Any]:
    details = row.get("details")
    normalized_details = details if isinstance(details, dict) else {}
    event = _as_text(row.get("event")) or "unknown"
    return {
        "event_id": f"audit.steps:{line_number}",
        "timestamp_ms": _as_int(row.get("timestamp_ms")),
        "agent_id": agent_id,
        "run_id": _as_nullable_text(row.get("run_id")),
        "session_id": _as_nullable_text(row.get("session_id")),
        "trigger_type": _as_text(row.get("trigger_type")) or "unknown",
        "event": event,
        "summary": _build_event_summary(event, normalized_details),
        "details": normalized_details,
        "source": "audit.steps",
    }


def _normalize_runs_event(
    row: dict[str, Any],
    *,
    agent_id: str,
    line_number: int,
) -> dict[str, Any]:
    event = _as_text(row.get("event")) or "unknown"
    details = {
        key: value
        for key, value in row.items()
        if key
        not in {
            "timestamp_ms",
            "event",
            "run_id",
            "session_id",
            "trigger_type",
        }
    }
    return {
        "event_id": f"runs.events:{line_number}",
        "timestamp_ms": _as_int(row.get("timestamp_ms")),
        "agent_id": agent_id,
        "run_id": _as_nullable_text(row.get("run_id")),
        "session_id": _as_nullable_text(row.get("session_id")),
        "trigger_type": _as_text(row.get("trigger_type")) or "unknown",
        "event": event,
        "summary": _build_event_summary(event, details),
        "details": details,
        "source": "runs.events",
    }


def _build_event_summary(event: str, details: dict[str, Any]) -> str:
    if event == "tool_start":
        tool = _as_text(details.get("tool")) or "tool"
        input_text = _as_text(details.get("input"))
        return _truncate(f"{tool} start {input_text}".strip())
    if event == "tool_end":
        tool = _as_text(details.get("tool"))
        output = _as_text(details.get("output"))
        prefix = f"{tool} completed" if tool else "tool completed"
        return _truncate(f"{prefix} {output}".strip())
    if event == "llm_start":
        model = _as_text(details.get("model")) or "model"
        prompts = _as_text(details.get("prompt_count"))
        suffix = f" prompts {prompts}" if prompts else ""
        return _truncate(f"{model}{suffix}".strip())
    if event == "llm_end":
        generations = _as_text(details.get("generation_count"))
        return _truncate(
            f"completed with {generations} generation(s)"
            if generations
            else "completed",
        )
    if event in {"llm_error", "error"}:
        error = _as_text(details.get("error"))
        return _truncate(error or "error")
    if details:
        return _truncate(json.dumps(details, ensure_ascii=True, sort_keys=True))
    return event


def _dedupe_signature(row: dict[str, Any]) -> str:
    details = row.get("details")
    details_text = (
        json.dumps(details, ensure_ascii=True, sort_keys=True)
        if isinstance(details, dict)
        else ""
    )
    return "|".join(
        [
            str(row.get("timestamp_ms", 0)),
            _as_text(row.get("event")),
            _as_text(row.get("run_id")),
            _as_text(row.get("session_id")),
            _as_text(row.get("trigger_type")),
            details_text,
        ]
    )


def _load_trace_events(agent_id: str) -> list[dict[str, Any]]:
    root = _require_agent_root(agent_id)
    audit_steps_path = root / "storage" / "audit" / "steps.jsonl"
    runs_events_path = root / "storage" / "runs_events.jsonl"

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    for line_number, row in _read_jsonl_rows(audit_steps_path):
        normalized = _normalize_audit_step(row, agent_id=agent_id, line_number=line_number)
        if normalized["timestamp_ms"] <= 0:
            continue
        signature = _dedupe_signature(normalized)
        seen.add(signature)
        rows.append(normalized)

    for line_number, row in _read_jsonl_rows(runs_events_path):
        normalized = _normalize_runs_event(row, agent_id=agent_id, line_number=line_number)
        if normalized["timestamp_ms"] <= 0:
            continue
        signature = _dedupe_signature(normalized)
        if signature in seen:
            continue
        seen.add(signature)
        rows.append(normalized)

    rows.sort(
        key=lambda item: (
            int(item.get("timestamp_ms", 0)),
            str(item.get("event_id", "")),
        ),
        reverse=True,
    )
    return rows


def _filter_trace_events(
    rows: list[dict[str, Any]],
    *,
    window: str,
    event: str,
    trigger: str,
    run_id: str,
    session_id: str,
    query: str,
) -> list[dict[str, Any]]:
    since_ms = int(time.time() * 1000) - WINDOW_TO_MS[window]
    normalized_query = query.strip().lower()

    filtered: list[dict[str, Any]] = []
    for row in rows:
        if int(row.get("timestamp_ms", 0)) < since_ms:
            continue
        if event != "all" and row.get("event") != event:
            continue
        if trigger != "all" and row.get("trigger_type") != trigger:
            continue
        if run_id and row.get("run_id") != run_id:
            continue
        if session_id and row.get("session_id") != session_id:
            continue
        if normalized_query:
            haystack = " ".join(
                [
                    _as_text(row.get("summary")),
                    json.dumps(row.get("details", {}), ensure_ascii=True, sort_keys=True),
                ]
            ).lower()
            if normalized_query not in haystack:
                continue
        filtered.append(row)
    return filtered


def _apply_cursor(
    rows: list[dict[str, Any]],
    cursor: str | None,
    limit: int,
) -> tuple[list[dict[str, Any]], str | None]:
    start_index = 0
    if cursor:
        timestamp_ms, event_id = _decode_cursor(cursor)
        match_index = next(
            (
                index
                for index, row in enumerate(rows)
                if int(row.get("timestamp_ms", 0)) == timestamp_ms
                and str(row.get("event_id", "")) == event_id
            ),
            None,
        )
        if match_index is None:
            raise ApiError(
                status_code=400,
                code="invalid_request",
                message="Trace cursor no longer matches available results",
            )
        start_index = match_index + 1

    page = rows[start_index : start_index + limit]
    if start_index + limit >= len(rows) or not page:
        return page, None

    last = page[-1]
    next_cursor = _encode_cursor(int(last["timestamp_ms"]), str(last["event_id"]))
    return page, next_cursor


def _build_event_counts_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for row in rows:
        event = _as_text(row.get("event")) or "unknown"
        counts[event] = counts.get(event, 0) + 1
    return {
        "total_matches": len(rows),
        "by_event": counts,
    }


@router.get("/agents/{agent_id}/traces/events")
async def list_trace_events(
    agent_id: str,
    window: str = Query(default="24h", pattern="^(1h|4h|12h|24h|7d|30d)$"),
    event: str = Query(default="all"),
    trigger: str = Query(default="all", pattern="^(all|chat|cron|heartbeat|unknown)$"),
    run_id: str = "",
    session_id: str = "",
    q: str = "",
    limit: int = Query(default=100, ge=1, le=200),
    cursor: str | None = None,
) -> dict[str, Any]:
    rows = _load_trace_events(agent_id)
    filtered = _filter_trace_events(
        rows,
        window=window,
        event=_as_text(event) or "all",
        trigger=trigger,
        run_id=_as_text(run_id),
        session_id=_as_text(session_id),
        query=q,
    )
    page, next_cursor = _apply_cursor(filtered, cursor, limit)
    return {
        "data": {
            "agent_id": agent_id,
            "window": window,
            "total": len(filtered),
            "next_cursor": next_cursor,
            "summary": _build_event_counts_summary(filtered),
            "events": page,
        }
    }


@router.get("/agents/{agent_id}/traces/events/{event_id}")
async def get_trace_event(agent_id: str, event_id: str) -> dict[str, Any]:
    rows = _load_trace_events(agent_id)
    for row in rows:
        if row.get("event_id") == event_id:
            return {"data": row}
    raise ApiError(status_code=404, code="not_found", message="Trace event not found")
