from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .base import ToolContext
from .contracts import ToolResult
from .path_guard import InvalidPathError, resolve_workspace_path
from .policy import PermissionLevel


@dataclass
class ReadFileTool:
    root_dir: Path
    max_chars_default: int = 10000

    name: str = "read_file"
    description: str = "Read workspace file content safely"
    permission_level: PermissionLevel = PermissionLevel.L0_READ

    def run(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        started = time.monotonic()
        path = str(args.get("path", ""))
        start_line = args.get("start_line")
        end_line = args.get("end_line")
        max_chars = int(args.get("max_chars", self.max_chars_default))

        try:
            resolved = resolve_workspace_path(self.root_dir, path)
        except InvalidPathError as exc:
            return ToolResult.failure(
                tool_name=self.name,
                code="E_INVALID_PATH",
                message=str(exc),
                duration_ms=int((time.monotonic() - started) * 1000),
                retryable=False,
            )

        if not resolved.exists() or not resolved.is_file():
            return ToolResult.failure(
                tool_name=self.name,
                code="E_NOT_FOUND",
                message=f"File not found: {path}",
                duration_ms=int((time.monotonic() - started) * 1000),
                retryable=False,
            )

        text = resolved.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()

        if isinstance(start_line, int) or isinstance(end_line, int):
            s = 1 if not isinstance(start_line, int) else max(1, start_line)
            e = len(lines) if not isinstance(end_line, int) else min(len(lines), end_line)
            text = "\n".join(lines[s - 1 : e])

        truncated = False
        if len(text) > max_chars:
            text = text[:max_chars] + "\n...[truncated]"
            truncated = True

        return ToolResult.success(
            tool_name=self.name,
            data={"path": path, "content": text, "truncated": truncated},
            duration_ms=int((time.monotonic() - started) * 1000),
            truncated=truncated,
        )
