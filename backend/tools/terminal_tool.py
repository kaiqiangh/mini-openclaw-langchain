from __future__ import annotations

import shlex
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .base import ToolContext
from .contracts import ToolResult
from .policy import PermissionLevel


@dataclass
class TerminalTool:
    root_dir: Path
    timeout_seconds: int = 30
    output_char_limit: int = 5000
    deny_fragments: tuple[str, ...] = (
        "rm -rf /",
        "mkfs",
        "shutdown",
        "reboot",
        ":(){ :|:& };:",
    )
    allow_commands: set[str] = field(
        default_factory=lambda: {
            "ls",
            "pwd",
            "cat",
            "echo",
            "rg",
            "find",
            "head",
            "tail",
            "wc",
            "python3",
            "pip",
            "npm",
            "node",
        }
    )

    name: str = "terminal"
    description: str = "Execute shell commands in workspace sandbox"
    permission_level: PermissionLevel = PermissionLevel.L3_SYSTEM

    def run(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        started = time.monotonic()
        raw_command = str(args.get("command", "")).strip()
        if not raw_command:
            return ToolResult.failure(
                tool_name=self.name,
                code="E_INVALID_ARGS",
                message="Missing required 'command' argument",
                duration_ms=int((time.monotonic() - started) * 1000),
            )

        lowered = raw_command.lower()
        if any(fragment in lowered for fragment in self.deny_fragments):
            return ToolResult.failure(
                tool_name=self.name,
                code="E_POLICY_DENIED",
                message="Command contains denied fragment",
                duration_ms=int((time.monotonic() - started) * 1000),
                details={"command": raw_command},
            )

        try:
            parts = shlex.split(raw_command)
        except ValueError as exc:
            return ToolResult.failure(
                tool_name=self.name,
                code="E_INVALID_ARGS",
                message=f"Invalid command syntax: {exc}",
                duration_ms=int((time.monotonic() - started) * 1000),
            )

        if not parts:
            return ToolResult.failure(
                tool_name=self.name,
                code="E_INVALID_ARGS",
                message="Command parsed to empty argv",
                duration_ms=int((time.monotonic() - started) * 1000),
            )

        if parts[0] not in self.allow_commands:
            return ToolResult.failure(
                tool_name=self.name,
                code="E_POLICY_DENIED",
                message=f"Command '{parts[0]}' is not allowlisted",
                duration_ms=int((time.monotonic() - started) * 1000),
            )

        try:
            result = subprocess.run(
                parts,
                cwd=str(self.root_dir),
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return ToolResult.failure(
                tool_name=self.name,
                code="E_TIMEOUT",
                message=f"Command timed out after {self.timeout_seconds}s",
                duration_ms=int((time.monotonic() - started) * 1000),
                retryable=True,
            )

        stdout = result.stdout or ""
        stderr = result.stderr or ""
        combined = f"{stdout}\n{stderr}".strip()
        truncated = False

        if len(combined) > self.output_char_limit:
            combined = combined[: self.output_char_limit] + "\n...[truncated]"
            truncated = True

        return ToolResult.success(
            tool_name=self.name,
            data={
                "exit_code": result.returncode,
                "stdout": stdout[: self.output_char_limit],
                "stderr": stderr[: self.output_char_limit],
                "combined": combined,
                "truncated": truncated,
            },
            duration_ms=int((time.monotonic() - started) * 1000),
            truncated=truncated,
        )
