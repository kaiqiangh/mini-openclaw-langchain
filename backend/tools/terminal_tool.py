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
    command_policy_mode: str = "auto"
    require_sandbox: bool = True
    allowed_command_prefixes: tuple[str, ...] = ()
    denied_command_prefixes: tuple[str, ...] = ()
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
    builtin_denied_command_prefixes: tuple[str, ...] = (
        "rm",
        "mkfs",
        "dd",
        "shutdown",
        "reboot",
        "halt",
        "poweroff",
        "systemctl",
        "launchctl",
        "sudo",
        "su",
        "doas",
        "sh",
        "bash",
        "zsh",
        "fish",
        "dash",
        "python -c",
        "python3 -c",
        "python -m pip",
        "python3 -m pip",
        "node -e",
        "node --eval",
        "perl -e",
        "ruby -e",
        "php -r",
        "osascript -e",
        "apt",
        "apt-get",
        "yum",
        "dnf",
        "brew",
        "pip install",
        "pip3 install",
        "npm install",
        "npm exec",
        "npx",
    )
    network_denied_command_prefixes: tuple[str, ...] = (
        "curl",
        "wget",
        "nc",
        "ncat",
        "netcat",
        "socat",
        "ssh",
        "scp",
        "rsync",
        "ftp",
        "telnet",
        "git clone",
        "git fetch",
        "git pull",
        "git push",
    )

    name: str = "terminal"
    description: str = "Execute terminal commands under sandbox and policy controls"
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
    def _normalize_prefix_tokens(
        prefixes: tuple[str, ...],
    ) -> list[tuple[str, list[str]]]:
        normalized: list[tuple[str, list[str]]] = []
        for prefix in prefixes:
            raw_prefix = str(prefix).strip()
            try:
                tokens = shlex.split(raw_prefix)
            except ValueError:
                continue
            if tokens:
                normalized.append((raw_prefix, [token.lower() for token in tokens]))
        return normalized

    @staticmethod
    def _match_prefix(
        argv: list[str], prefixes: list[tuple[str, list[str]]]
    ) -> str | None:
        lowered_argv = [part.lower() for part in argv]
        for raw_prefix, prefix in prefixes:
            if len(argv) < len(prefix):
                continue
            if lowered_argv[: len(prefix)] == prefix:
                return raw_prefix
        return None

    @staticmethod
    def _normalize_policy_mode(value: str) -> str:
        normalized = str(value).strip().lower() or "auto"
        if normalized in {"allowlist", "denylist"}:
            return normalized
        return "auto"

    def _effective_policy_mode(self, sandbox_backend_id: str) -> str:
        mode = self._normalize_policy_mode(self.command_policy_mode)
        if mode != "auto":
            return mode
        if sandbox_backend_id == "unsafe_none":
            return "allowlist"
        return "denylist"

    def _policy_failure(
        self,
        *,
        started: float,
        message: str,
        command: str,
        effective_policy_mode: str | None = None,
        matched_policy_rule: str | None = None,
    ) -> ToolResult:
        details: dict[str, Any] = {"command": command}
        if effective_policy_mode is not None:
            details["effective_policy_mode"] = effective_policy_mode
        if matched_policy_rule is not None:
            details["matched_policy_rule"] = matched_policy_rule
        return ToolResult.failure(
            tool_name=self.name,
            code="E_POLICY_DENIED",
            message=message,
            duration_ms=int((time.monotonic() - started) * 1000),
            details=details,
        )

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
            "command_policy_mode": self._normalize_policy_mode(
                self.command_policy_mode
            ),
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
            return self._policy_failure(
                started=started,
                message="Command contains denied fragment",
                command=raw_command,
            )

        if not self.allow_shell_syntax and self._contains_shell_syntax(raw_command):
            return self._policy_failure(
                started=started,
                message="Shell syntax is not allowed for terminal commands",
                command=raw_command,
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

        effective_policy_mode = self._effective_policy_mode(sandbox.backend_id)
        built_in_denied_prefixes = self._normalize_prefix_tokens(
            self.builtin_denied_command_prefixes
        )
        matched_prefix = self._match_prefix(argv, built_in_denied_prefixes)
        if matched_prefix is not None:
            return self._policy_failure(
                started=started,
                message="Command prefix is denied by terminal policy",
                command=raw_command,
                effective_policy_mode=effective_policy_mode,
                matched_policy_rule=matched_prefix,
            )

        custom_denied_prefixes = self._normalize_prefix_tokens(
            self.denied_command_prefixes
        )
        matched_prefix = self._match_prefix(argv, custom_denied_prefixes)
        if matched_prefix is not None:
            return self._policy_failure(
                started=started,
                message="Command prefix is denied by runtime configuration",
                command=raw_command,
                effective_policy_mode=effective_policy_mode,
                matched_policy_rule=matched_prefix,
            )

        if not self.allow_network:
            network_denied_prefixes = self._normalize_prefix_tokens(
                self.network_denied_command_prefixes
            )
            matched_prefix = self._match_prefix(argv, network_denied_prefixes)
            if matched_prefix is not None:
                return self._policy_failure(
                    started=started,
                    message="Network-capable command is denied when terminal network access is disabled",
                    command=raw_command,
                    effective_policy_mode=effective_policy_mode,
                    matched_policy_rule=matched_prefix,
                )

        if effective_policy_mode == "allowlist":
            allowed_prefixes = self._normalize_prefix_tokens(
                self.allowed_command_prefixes
            )
            matched_prefix = self._match_prefix(argv, allowed_prefixes)
            if matched_prefix is None:
                return self._policy_failure(
                    started=started,
                    message="Command is not allowlisted",
                    command=raw_command,
                    effective_policy_mode=effective_policy_mode,
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
                "effective_policy_mode": effective_policy_mode,
            },
            duration_ms=int((time.monotonic() - started) * 1000),
            truncated=truncated,
        )
