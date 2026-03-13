from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite import SqliteSaver

from graph.checkpoint_serde import build_checkpoint_serializer
from graph.session_manager import SessionManager

from .base import ToolContext
from .contracts import ToolResult
from .policy import PermissionLevel
from .workspace_resolver import resolve_agent_root


_SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")


def _load_checkpoint_messages(
    agent_root: Path, session_id: str
) -> tuple[list[dict[str, Any]], str, dict[str, Any] | None]:
    db_path = agent_root / "storage" / "langgraph_checkpoints.sqlite"
    if not db_path.exists():
        return [], "", None
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    try:
        saver = SqliteSaver(conn, serde=build_checkpoint_serializer())
        checkpoint = saver.get_tuple({"configurable": {"thread_id": session_id}})
        if checkpoint is None or not isinstance(checkpoint.checkpoint, dict):
            return [], "", None
        channel_values = checkpoint.checkpoint.get("channel_values", {})
        if not isinstance(channel_values, dict):
            return [], "", None
        messages = channel_values.get("messages", [])
        compressed_context = str(channel_values.get("compressed_context", "")).strip()
        live_response = (
            dict(channel_values.get("live_response"))
            if isinstance(channel_values.get("live_response"), dict)
            else None
        )
        normalized_messages = [
            dict(item) for item in messages if isinstance(item, dict)
        ]
        return normalized_messages, compressed_context, live_response
    finally:
        conn.close()


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

        (
            checkpoint_messages,
            checkpoint_compressed_context,
            checkpoint_live_response,
        ) = _load_checkpoint_messages(agent_root, session_id)
        raw_messages = checkpoint_messages
        messages = (
            manager.with_live_response(
                raw_messages,
                {"live_response": checkpoint_live_response},
            )
            if include_live
            else raw_messages
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
                "compressed_context": checkpoint_compressed_context
                or str(session.get("compressed_context", "")),
                "truncated": truncated,
            },
            duration_ms=int((time.monotonic() - started) * 1000),
            truncated=truncated,
        )

    def audit_metadata(self) -> dict[str, Any]:
        return {"resource": "session_history", "scope": "agent"}
