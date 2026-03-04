from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from graph.session_manager import SessionManager

from .base import ToolContext
from .contracts import ToolResult
from .policy import PermissionLevel
from .workspace_resolver import resolve_agent_root


_VALID_SCOPES = {"active", "archived", "all"}


@dataclass
class SessionsListTool:
    runtime_root: Path
    config_base_dir: Path | None = None
    limit_default: int = 100
    limit_max: int = 1000

    name: str = "sessions_list"
    description: str = "List sessions for an agent (active, archived, or all)"
    permission_level: PermissionLevel = PermissionLevel.L0_READ

    def run(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        _ = context
        started = time.monotonic()
        scope = str(args.get("scope", "active")).strip().lower() or "active"
        if scope not in _VALID_SCOPES:
            return ToolResult.failure(
                tool_name=self.name,
                code="E_INVALID_ARGS",
                message="scope must be one of: active, archived, all",
                duration_ms=int((time.monotonic() - started) * 1000),
            )

        limit = int(args.get("limit", self.limit_default))
        limit = max(1, min(self.limit_max, limit))
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

        manager = SessionManager(agent_root)
        sessions = manager.list_sessions(scope=scope)[:limit]
        return ToolResult.success(
            tool_name=self.name,
            data={
                "agent_id": agent_id,
                "scope": scope,
                "sessions": sessions,
                "count": len(sessions),
                "limit": limit,
            },
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    def audit_metadata(self) -> dict[str, Any]:
        return {"resource": "sessions", "scope": "agent"}
