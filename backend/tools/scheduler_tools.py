from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config import load_runtime_config

from .base import ToolContext
from .contracts import ToolResult
from .policy import PermissionLevel
from .workspace_resolver import resolve_agent_root


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default
    return value


def _read_jsonl(path: Path, limit: int) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        lines = [
            line
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except Exception:
        return []

    rows: list[dict[str, Any]] = []
    for line in reversed(lines):
        try:
            parsed = json.loads(line)
        except Exception:
            continue
        if isinstance(parsed, dict):
            rows.append(parsed)
            if len(rows) >= limit:
                break
    return rows


@dataclass
class SchedulerCronJobsTool:
    runtime_root: Path
    config_base_dir: Path | None = None

    name: str = "scheduler_cron_jobs"
    description: str = "Read cron job configuration for an agent"
    permission_level: PermissionLevel = PermissionLevel.L0_READ

    def run(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        _ = context
        started = time.monotonic()
        requested_agent_id = args.get("agent_id")
        if requested_agent_id is not None and not isinstance(requested_agent_id, str):
            return ToolResult.failure(
                tool_name=self.name,
                code="E_INVALID_ARGS",
                message="agent_id must be a string",
                duration_ms=int((time.monotonic() - started) * 1000),
            )
        try:
            agent_id, agent_root = resolve_agent_root(
                runtime_root=self.runtime_root,
                config_base_dir=self.config_base_dir,
                requested_agent_id=requested_agent_id,
            )
        except ValueError as exc:
            return ToolResult.failure(
                tool_name=self.name,
                code="E_INVALID_ARGS",
                message=str(exc),
                duration_ms=int((time.monotonic() - started) * 1000),
            )
        except FileNotFoundError as exc:
            return ToolResult.failure(
                tool_name=self.name,
                code="E_NOT_FOUND",
                message=str(exc),
                duration_ms=int((time.monotonic() - started) * 1000),
            )

        payload = _read_json(agent_root / "storage" / "cron_jobs.json", {"jobs": []})
        jobs = payload.get("jobs", []) if isinstance(payload, dict) else []
        if not isinstance(jobs, list):
            jobs = []

        return ToolResult.success(
            tool_name=self.name,
            data={"agent_id": agent_id, "jobs": jobs, "count": len(jobs)},
            duration_ms=int((time.monotonic() - started) * 1000),
        )


@dataclass
class SchedulerCronRunsTool:
    runtime_root: Path
    config_base_dir: Path | None = None
    limit_default: int = 100

    name: str = "scheduler_cron_runs"
    description: str = "Read recent cron run events for an agent"
    permission_level: PermissionLevel = PermissionLevel.L0_READ

    def run(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        _ = context
        started = time.monotonic()
        requested_agent_id = args.get("agent_id")
        if requested_agent_id is not None and not isinstance(requested_agent_id, str):
            return ToolResult.failure(
                tool_name=self.name,
                code="E_INVALID_ARGS",
                message="agent_id must be a string",
                duration_ms=int((time.monotonic() - started) * 1000),
            )
        limit = int(args.get("limit", self.limit_default))
        limit = max(1, min(5000, limit))

        try:
            agent_id, agent_root = resolve_agent_root(
                runtime_root=self.runtime_root,
                config_base_dir=self.config_base_dir,
                requested_agent_id=requested_agent_id,
            )
        except ValueError as exc:
            return ToolResult.failure(
                tool_name=self.name,
                code="E_INVALID_ARGS",
                message=str(exc),
                duration_ms=int((time.monotonic() - started) * 1000),
            )
        except FileNotFoundError as exc:
            return ToolResult.failure(
                tool_name=self.name,
                code="E_NOT_FOUND",
                message=str(exc),
                duration_ms=int((time.monotonic() - started) * 1000),
            )

        rows = _read_jsonl(agent_root / "storage" / "cron_runs.jsonl", limit=limit)
        return ToolResult.success(
            tool_name=self.name,
            data={"agent_id": agent_id, "runs": rows, "count": len(rows), "limit": limit},
            duration_ms=int((time.monotonic() - started) * 1000),
        )


@dataclass
class SchedulerHeartbeatStatusTool:
    runtime_root: Path
    config_base_dir: Path | None = None

    name: str = "scheduler_heartbeat_status"
    description: str = "Read heartbeat scheduler configuration for an agent"
    permission_level: PermissionLevel = PermissionLevel.L0_READ

    def run(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        _ = context
        started = time.monotonic()
        requested_agent_id = args.get("agent_id")
        if requested_agent_id is not None and not isinstance(requested_agent_id, str):
            return ToolResult.failure(
                tool_name=self.name,
                code="E_INVALID_ARGS",
                message="agent_id must be a string",
                duration_ms=int((time.monotonic() - started) * 1000),
            )

        try:
            agent_id, agent_root = resolve_agent_root(
                runtime_root=self.runtime_root,
                config_base_dir=self.config_base_dir,
                requested_agent_id=requested_agent_id,
            )
        except ValueError as exc:
            return ToolResult.failure(
                tool_name=self.name,
                code="E_INVALID_ARGS",
                message=str(exc),
                duration_ms=int((time.monotonic() - started) * 1000),
            )
        except FileNotFoundError as exc:
            return ToolResult.failure(
                tool_name=self.name,
                code="E_NOT_FOUND",
                message=str(exc),
                duration_ms=int((time.monotonic() - started) * 1000),
            )

        runtime = load_runtime_config(agent_root / "config.json")
        heartbeat = runtime.heartbeat
        prompt_file = agent_root / "workspace" / "HEARTBEAT.md"
        prompt_exists = prompt_file.exists()

        return ToolResult.success(
            tool_name=self.name,
            data={
                "agent_id": agent_id,
                "config": {
                    "enabled": heartbeat.enabled,
                    "interval_seconds": heartbeat.interval_seconds,
                    "timezone": heartbeat.timezone,
                    "active_start_hour": heartbeat.active_start_hour,
                    "active_end_hour": heartbeat.active_end_hour,
                    "session_id": heartbeat.session_id,
                },
                "prompt_file": str(prompt_file),
                "prompt_exists": prompt_exists,
            },
            duration_ms=int((time.monotonic() - started) * 1000),
        )


@dataclass
class SchedulerHeartbeatRunsTool:
    runtime_root: Path
    config_base_dir: Path | None = None
    limit_default: int = 100

    name: str = "scheduler_heartbeat_runs"
    description: str = "Read recent heartbeat run events for an agent"
    permission_level: PermissionLevel = PermissionLevel.L0_READ

    def run(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        _ = context
        started = time.monotonic()
        requested_agent_id = args.get("agent_id")
        if requested_agent_id is not None and not isinstance(requested_agent_id, str):
            return ToolResult.failure(
                tool_name=self.name,
                code="E_INVALID_ARGS",
                message="agent_id must be a string",
                duration_ms=int((time.monotonic() - started) * 1000),
            )
        limit = int(args.get("limit", self.limit_default))
        limit = max(1, min(5000, limit))

        try:
            agent_id, agent_root = resolve_agent_root(
                runtime_root=self.runtime_root,
                config_base_dir=self.config_base_dir,
                requested_agent_id=requested_agent_id,
            )
        except ValueError as exc:
            return ToolResult.failure(
                tool_name=self.name,
                code="E_INVALID_ARGS",
                message=str(exc),
                duration_ms=int((time.monotonic() - started) * 1000),
            )
        except FileNotFoundError as exc:
            return ToolResult.failure(
                tool_name=self.name,
                code="E_NOT_FOUND",
                message=str(exc),
                duration_ms=int((time.monotonic() - started) * 1000),
            )

        rows = _read_jsonl(agent_root / "storage" / "heartbeat_runs.jsonl", limit=limit)
        return ToolResult.success(
            tool_name=self.name,
            data={"agent_id": agent_id, "runs": rows, "count": len(rows), "limit": limit},
            duration_ms=int((time.monotonic() - started) * 1000),
        )
