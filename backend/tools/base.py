from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .contracts import ToolResult
from .policy import PermissionLevel


@dataclass
class ToolContext:
    workspace_root: Path
    trigger_type: str
    explicit_enabled_tools: tuple[str, ...] = ()
    run_id: str | None = None
    session_id: str | None = None


class MiniTool(Protocol):
    name: str
    description: str
    permission_level: PermissionLevel

    def run(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        ...
