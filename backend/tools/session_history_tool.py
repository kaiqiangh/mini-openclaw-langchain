from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from graph.session_manager import SessionManager

from .base import ToolContext
from .contracts import ToolResult
from .policy import PermissionLevel
from .workspace_resolver import resolve_agent_root


_SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")


@dataclass
class SessionHistoryTool:
    runtime_root: Path
    config_base_dir: Path | None = None
    max_messages_default: int = 200

    name: str = "session_history"
    description: str = "Read session message history for an agent"
    permission_level: PermissionLevel = PermissionLevel.L0_READ

    def run(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        _ = context
        started = time.monotonic()
        session_id = str(args.get("session_id", "")).strip()
        if not _SESSION_ID_PATTERN.fullmatch(session_id):
            return ToolResult.failure(
                tool_name=self.name,
                code="E_INVALID_ARGS",
                message="session_id must match [A-Za-z0-9_.-]{1,128}",
                duration_ms=int((time.monotonic() - started) * 1000),
            )

        requested_agent_id = args.get("agent_id")
        if requested_agent_id is not None and not isinstance(requested_agent_id, str):
            return ToolResult.failure(
                tool_name=self.name,
                code="E_INVALID_ARGS",
                message="agent_id must be a string",
                duration_ms=int((time.monotonic() - started) * 1000),
            )

        archived = bool(args.get("archived", False))
        include_live = bool(args.get("include_live", True))
        max_messages = int(args.get("max_messages", self.max_messages_default))
        max_messages = max(1, min(5000, max_messages))

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
        try:
            session = manager.load_session(session_id, archived=archived)
        except FileNotFoundError as exc:
            return ToolResult.failure(
                tool_name=self.name,
                code="E_NOT_FOUND",
                message=str(exc),
                duration_ms=int((time.monotonic() - started) * 1000),
            )

        raw_messages = list(session.get("messages", []))
        messages = (
            manager.with_live_response(raw_messages, session) if include_live else raw_messages
        )
        truncated = False
        if len(messages) > max_messages:
            messages = messages[-max_messages:]
            truncated = True

        return ToolResult.success(
            tool_name=self.name,
            data={
                "agent_id": agent_id,
                "session_id": session_id,
                "archived": archived,
                "message_count": len(messages),
                "messages": messages,
                "compressed_context": str(session.get("compressed_context", "")),
                "truncated": truncated,
            },
            duration_ms=int((time.monotonic() - started) * 1000),
            truncated=truncated,
        )

    def audit_metadata(self) -> dict[str, Any]:
        return {"resource": "session_history", "scope": "agent"}
