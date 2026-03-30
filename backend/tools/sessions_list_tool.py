from __future__ import annotations

import json
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

    @staticmethod
    def _list_sessions_sync(manager: SessionManager, *, scope: str = "active") -> list[dict[str, Any]]:
        """Sync session listing for use in tool context (no event loop)."""
        include_active = scope in {"active", "all"}
        include_archived = scope in {"archived", "all"}
        items: list[dict[str, Any]] = []

        def _read_session_meta(path: Path) -> dict[str, Any] | None:
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    return raw
            except Exception:
                pass
            return None

        if include_active:
            for path in sorted(manager.sessions_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
                if not path.is_file():
                    continue
                meta = _read_session_meta(path)
                if meta is None:
                    continue
                items.append({
                    "session_id": path.stem,
                    "title": str(meta.get("title", "New Session")),
                    "created_at": float(meta.get("created_at", 0)),
                    "updated_at": float(meta.get("updated_at", 0)),
                    "archived": False,
                })
        if include_archived:
            for path in sorted(manager.archived_sessions_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
                if not path.is_file():
                    continue
                meta = _read_session_meta(path)
                if meta is None:
                    continue
                items.append({
                    "session_id": path.stem,
                    "title": str(meta.get("title", "New Session")),
                    "created_at": float(meta.get("created_at", 0)),
                    "updated_at": float(meta.get("updated_at", 0)),
                    "archived": True,
                })
        items.sort(key=lambda item: item["updated_at"], reverse=True)
        return items

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
        sessions = self._list_sessions_sync(manager, scope=scope)[:limit]
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
