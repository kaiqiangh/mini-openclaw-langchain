from __future__ import annotations

import os
import shlex
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .base import ToolContext
from .contracts import ToolResult
from .policy import PermissionLevel
from .sandbox import SandboxUnavailableError, resolve_sandbox


@dataclass
class TerminalTool:
    root_dir: Path
    timeout_seconds: int = 30
    max_timeout_seconds: int = 300
    output_char_limit: int = 5000
    sandbox_mode: str = "hybrid_auto"
    require_sandbox: bool = True
    allowed_command_prefixes: tuple[str, ...] = ()
    allow_network: bool = False
    allow_shell_syntax: bool = False
    max_args: int = 32
    max_arg_length: int = 256
    deny_fragments: tuple[str, ...] = (
        "rm -rf /",
        "mkfs",
        "shutdown",
        "reboot",
        ":(){ :|:& };:",
    )

    name: str = "terminal"
    description: str = (
        "Execute allowlisted commands in a constrained process sandbox"
    )
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
        sensitive_markers = (
            "KEY",
            "TOKEN",
            "SECRET",
            "PASSWORD",
            "AUTH",
            "CREDENTIAL",
            "COOKIE",
        )
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

    @staticmethod
    def _contains_shell_syntax(command: str) -> bool:
        if "$(" in command or "`" in command:
            return True
        lexer = shlex.shlex(command, posix=True, punctuation_chars="|&;<>")
        lexer.whitespace_split = True
        forbidden_operators = {"|", "||", "&", "&&", ";", "<", ">", ">>", "<<"}
        return any(token in forbidden_operators for token in lexer)

    @staticmethod
    def _normalize_prefix_tokens(prefixes: tuple[str, ...]) -> list[list[str]]:
        normalized: list[list[str]] = []
        for prefix in prefixes:
            try:
                tokens = shlex.split(str(prefix))
            except ValueError:
                continue
            if tokens:
                normalized.append(tokens)
        return normalized

    @staticmethod
    def _matches_allowlist(
        argv: list[str], allowed_prefixes: list[list[str]]
    ) -> bool:
        if not allowed_prefixes:
            return False
        for prefix in allowed_prefixes:
            if len(argv) < len(prefix):
                continue
            if argv[: len(prefix)] == prefix:
                return True
        return False

    @staticmethod
    def _kill_process_group(process: subprocess.Popen[str]) -> None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except Exception:
            try:
                process.kill()
            except Exception:
                return

    def audit_metadata(self) -> dict[str, Any]:
        return {
            "sandbox_mode": self.sandbox_mode,
            "require_sandbox": self.require_sandbox,
            "allow_network": self.allow_network,
            "allow_shell_syntax": self.allow_shell_syntax,
        }

    def run(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        _ = context
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

        if not self.allow_shell_syntax and self._contains_shell_syntax(raw_command):
            return ToolResult.failure(
                tool_name=self.name,
                code="E_POLICY_DENIED",
                message="Shell syntax is not allowed for terminal commands",
                duration_ms=int((time.monotonic() - started) * 1000),
                details={"command": raw_command},
            )

        try:
            argv = shlex.split(raw_command)
        except ValueError:
            return ToolResult.failure(
                tool_name=self.name,
                code="E_INVALID_ARGS",
                message="Command parsing failed",
                duration_ms=int((time.monotonic() - started) * 1000),
                details={"command": raw_command},
            )
        if not argv:
            return ToolResult.failure(
                tool_name=self.name,
                code="E_INVALID_ARGS",
                message="Missing executable in command",
                duration_ms=int((time.monotonic() - started) * 1000),
            )
        if len(argv) > self.max_args:
            return ToolResult.failure(
                tool_name=self.name,
                code="E_INVALID_ARGS",
                message=f"Command exceeds max argument count ({self.max_args})",
                duration_ms=int((time.monotonic() - started) * 1000),
            )
        if any(len(part) > self.max_arg_length for part in argv):
            return ToolResult.failure(
                tool_name=self.name,
                code="E_INVALID_ARGS",
                message=f"Command argument exceeds max length ({self.max_arg_length})",
                duration_ms=int((time.monotonic() - started) * 1000),
            )

        allowed_prefixes = self._normalize_prefix_tokens(self.allowed_command_prefixes)
        if not self._matches_allowlist(argv, allowed_prefixes):
            return ToolResult.failure(
                tool_name=self.name,
                code="E_POLICY_DENIED",
                message="Command is not allowlisted",
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
            sandbox = resolve_sandbox(
                mode=self.sandbox_mode,
                root_dir=self.root_dir,
                require_sandbox=self.require_sandbox,
                allow_network=self.allow_network,
            )
        except SandboxUnavailableError as exc:
            return ToolResult.failure(
                tool_name=self.name,
                code="E_SANDBOX_UNAVAILABLE",
                message=str(exc),
                duration_ms=int((time.monotonic() - started) * 1000),
            )

        command = sandbox.wrap_command(argv)
        try:
            process = subprocess.Popen(
                command,
                cwd=str(self.root_dir),
                env=self._sanitized_env(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
            try:
                stdout, stderr = process.communicate(timeout=effective_timeout)
            except subprocess.TimeoutExpired:
                self._kill_process_group(process)
                process.wait()
                return ToolResult.failure(
                    tool_name=self.name,
                    code="E_TIMEOUT",
                    message=f"Command timed out after {effective_timeout}s",
                    duration_ms=int((time.monotonic() - started) * 1000),
                    retryable=True,
                    details={"sandbox_backend": sandbox.backend_id},
                )
        except OSError as exc:
            return ToolResult.failure(
                tool_name=self.name,
                code="E_EXEC",
                message="Failed to execute command",
                duration_ms=int((time.monotonic() - started) * 1000),
                details={"exception": str(exc), "sandbox_backend": sandbox.backend_id},
            )

        stdout = stdout or ""
        stderr = stderr or ""
        stderr_lower = stderr.lower()
        if (
            sandbox.backend_id == "darwin_sandbox_exec"
            and process.returncode != 0
            and stderr_lower.startswith("sandbox-exec:")
        ):
            return ToolResult.failure(
                tool_name=self.name,
                code="E_SANDBOX_REQUIRED",
                message="Terminal sandbox enforcement failed",
                duration_ms=int((time.monotonic() - started) * 1000),
                details={"stderr": stderr[:512], "sandbox_backend": sandbox.backend_id},
            )
        if (
            sandbox.backend_id == "linux_bwrap"
            and process.returncode != 0
            and "bwrap:" in stderr_lower
        ):
            return ToolResult.failure(
                tool_name=self.name,
                code="E_SANDBOX_REQUIRED",
                message="Terminal sandbox enforcement failed",
                duration_ms=int((time.monotonic() - started) * 1000),
                details={"stderr": stderr[:512], "sandbox_backend": sandbox.backend_id},
            )

        combined = f"{stdout}\n{stderr}".strip()
        truncated = False

        if len(combined) > self.output_char_limit:
            combined = combined[: self.output_char_limit] + "\n...[truncated]"
            truncated = True

        return ToolResult.success(
            tool_name=self.name,
            data={
                "exit_code": process.returncode,
                "stdout": stdout[: self.output_char_limit],
                "stderr": stderr[: self.output_char_limit],
                "combined": combined,
                "truncated": truncated,
                "timeout_seconds": effective_timeout,
                "sandbox_backend": sandbox.backend_id,
                "sandbox_mode": sandbox.mode,
            },
            duration_ms=int((time.monotonic() - started) * 1000),
            truncated=truncated,
        )
