from __future__ import annotations

import io
import time
from contextlib import redirect_stdout
from dataclasses import dataclass
from typing import Any

from .base import ToolContext
from .contracts import ToolResult
from .policy import PermissionLevel


@dataclass
class PythonReplTool:
    output_char_limit: int = 5000

    name: str = "python_repl"
    description: str = "Execute Python snippets in constrained REPL scope"
    permission_level: PermissionLevel = PermissionLevel.L1_WRITE

    def run(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        _ = context
        started = time.monotonic()
        code = str(args.get("code", "")).strip()

        if not code:
            return ToolResult.failure(
                tool_name=self.name,
                code="E_INVALID_ARGS",
                message="Missing required 'code' argument",
                duration_ms=int((time.monotonic() - started) * 1000),
            )

        safe_globals = {
            "__builtins__": {
                "abs": abs,
                "all": all,
                "any": any,
                "len": len,
                "min": min,
                "max": max,
                "sum": sum,
                "sorted": sorted,
                "range": range,
                "print": print,
            }
        }
        safe_locals: dict[str, Any] = {}

        buffer = io.StringIO()
        try:
            with redirect_stdout(buffer):
                exec(code, safe_globals, safe_locals)
        except Exception as exc:  # noqa: BLE001
            return ToolResult.failure(
                tool_name=self.name,
                code="E_EXEC",
                message="Python execution failed",
                duration_ms=int((time.monotonic() - started) * 1000),
                details={"exception": str(exc)},
            )

        output = buffer.getvalue().strip()
        truncated = False
        if len(output) > self.output_char_limit:
            output = output[: self.output_char_limit] + "\n...[truncated]"
            truncated = True

        return ToolResult.success(
            tool_name=self.name,
            data={"output": output, "truncated": truncated},
            duration_ms=int((time.monotonic() - started) * 1000),
            truncated=truncated,
        )
