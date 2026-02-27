from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .base import ToolContext
from .contracts import ToolResult
from .path_guard import InvalidPathError, resolve_workspace_path
from .policy import PermissionLevel


def _slice_text(
    text: str,
    *,
    start_line: Any,
    end_line: Any,
) -> str:
    lines = text.splitlines()
    if not isinstance(start_line, int) and not isinstance(end_line, int):
        return text
    s = 1 if not isinstance(start_line, int) else max(1, start_line)
    e = len(lines) if not isinstance(end_line, int) else min(len(lines), end_line)
    return "\n".join(lines[s - 1 : e])


@dataclass
class ReadFilesTool:
    root_dir: Path
    max_chars_default: int = 10000
    max_paths: int = 32

    name: str = "read_files"
    description: str = "Read multiple workspace files safely"
    permission_level: PermissionLevel = PermissionLevel.L0_READ

    def run(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        _ = context
        started = time.monotonic()
        raw_paths = args.get("paths")
        if not isinstance(raw_paths, list) or not raw_paths:
            return ToolResult.failure(
                tool_name=self.name,
                code="E_INVALID_ARGS",
                message="Missing required 'paths' list argument",
                duration_ms=int((time.monotonic() - started) * 1000),
            )

        if len(raw_paths) > self.max_paths:
            return ToolResult.failure(
                tool_name=self.name,
                code="E_INVALID_ARGS",
                message=f"paths length exceeds max of {self.max_paths}",
                duration_ms=int((time.monotonic() - started) * 1000),
            )

        start_line = args.get("start_line")
        end_line = args.get("end_line")
        max_chars = int(args.get("max_chars", self.max_chars_default))
        max_chars = max(1, max_chars)

        results: list[dict[str, Any]] = []
        for raw_path in raw_paths:
            path = str(raw_path)
            try:
                resolved = resolve_workspace_path(self.root_dir, path)
            except InvalidPathError as exc:
                results.append(
                    {
                        "ok": False,
                        "path": path,
                        "error": {"code": "E_INVALID_PATH", "message": str(exc)},
                    }
                )
                continue

            if not resolved.exists() or not resolved.is_file():
                results.append(
                    {
                        "ok": False,
                        "path": path,
                        "error": {"code": "E_NOT_FOUND", "message": f"File not found: {path}"},
                    }
                )
                continue

            text = resolved.read_text(encoding="utf-8", errors="replace")
            text = _slice_text(text, start_line=start_line, end_line=end_line)

            truncated = False
            if len(text) > max_chars:
                text = text[:max_chars] + "\n...[truncated]"
                truncated = True

            results.append(
                {
                    "ok": True,
                    "path": path,
                    "content": text,
                    "truncated": truncated,
                }
            )

        partial = any(not item.get("ok", False) for item in results)
        return ToolResult.success(
            tool_name=self.name,
            data={"results": results, "partial": partial},
            duration_ms=int((time.monotonic() - started) * 1000),
        )
