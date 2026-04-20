from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from graph.session_manager import count_session_files

from .base import ToolContext
from .contracts import ToolResult
from .policy import PermissionLevel
from .workspace_resolver import list_agent_roots, resolve_project_root


@dataclass
class AgentsListTool:
    runtime_root: Path
    config_base_dir: Path | None = None

    name: str = "agents_list"
    description: str = "List available agents in this workspace"
    permission_level: PermissionLevel = PermissionLevel.L0_READ

    def run(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        _ = args, context
        started = time.monotonic()
        project_root = resolve_project_root(self.runtime_root, self.config_base_dir)

        agents: list[dict[str, Any]] = []
        for agent_id, root in list_agent_roots(project_root):
            sessions_dir = root / "sessions"
            active_sessions = count_session_files(sessions_dir, archived=False)
            archived_sessions = count_session_files(sessions_dir, archived=True)
            stat = root.stat()
            agents.append(
                {
                    "agent_id": agent_id,
                    "path": str(root),
                    "created_at": float(stat.st_ctime),
                    "updated_at": float(stat.st_mtime),
                    "active_sessions": active_sessions,
                    "archived_sessions": archived_sessions,
                }
            )

        return ToolResult.success(
            tool_name=self.name,
            data={
                "agents": agents,
                "count": len(agents),
                "project_root": str(project_root),
            },
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    def audit_metadata(self) -> dict[str, Any]:
        return {"resource": "agents", "scope": "workspace"}
