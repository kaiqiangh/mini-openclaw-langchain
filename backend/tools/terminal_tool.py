from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .base import ToolContext
from .contracts import ToolResult
from .policy import PermissionLevel


@dataclass
class TerminalTool:
    root_dir: Path
    timeout_seconds: int = 30
    max_timeout_seconds: int = 300
    output_char_limit: int = 5000
    shell_mode: bool = True
    deny_fragments: tuple[str, ...] = (
        "rm -rf /",
        "mkfs",
        "shutdown",
        "reboot",
        ":(){ :|:& };:",
    )

    name: str = "terminal"
    description: str = "Execute shell commands in workspace sandbox"
    permission_level: PermissionLevel = PermissionLevel.L3_SYSTEM

    @staticmethod
    def _sanitized_env() -> dict[str, str]:
        keep_exact = {
            "PATH",
            "HOME",
            "PWD",
            "SHELL",
            "LANG",
            "LC_ALL",
            "LC_CTYPE",
            "TERM",
            "TMPDIR",
            "USER",
            "LOGNAME",
            "TZ",
        }
        sensitive_markers = ("KEY", "TOKEN", "SECRET", "PASSWORD", "AUTH", "CREDENTIAL", "COOKIE")
        sanitized: dict[str, str] = {}
        for key, value in os.environ.items():
            upper = key.upper()
            if key in keep_exact:
                sanitized[key] = value
                continue
            if any(marker in upper for marker in sensitive_markers):
                continue
            sanitized[key] = value
        return sanitized

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

        requested_timeout = args.get("timeout")
        effective_timeout = self.timeout_seconds
        if requested_timeout is not None:
            try:
                requested = int(requested_timeout)
            except (TypeError, ValueError):
                return ToolResult.failure(
                    tool_name=self.name,
                    code="E_INVALID_ARGS",
                    message="'timeout' must be an integer number of seconds",
                    duration_ms=int((time.monotonic() - started) * 1000),
                )
            effective_timeout = max(1, min(requested, self.max_timeout_seconds))

        try:
            if self.shell_mode:
                result = subprocess.run(
                    raw_command,
                    cwd=str(self.root_dir),
                    shell=True,
                    executable="/bin/bash",
                    env=self._sanitized_env(),
                    capture_output=True,
                    text=True,
                    timeout=effective_timeout,
                    check=False,
                )
            else:
                return ToolResult.failure(
                    tool_name=self.name,
                    code="E_INTERNAL",
                    message="Only shell execution mode is supported",
                    duration_ms=int((time.monotonic() - started) * 1000),
                )
        except subprocess.TimeoutExpired:
            return ToolResult.failure(
                tool_name=self.name,
                code="E_TIMEOUT",
                message=f"Command timed out after {effective_timeout}s",
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
                "timeout_seconds": effective_timeout,
            },
            duration_ms=int((time.monotonic() - started) * 1000),
            truncated=truncated,
        )
