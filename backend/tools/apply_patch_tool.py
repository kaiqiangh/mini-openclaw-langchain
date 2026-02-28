from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .base import ToolContext
from .contracts import ToolResult
from .path_guard import InvalidPathError, resolve_workspace_path
from .policy import PermissionLevel


def _normalize_patch_path(raw: str) -> str | None:
    candidate = raw.strip()
    if "\t" in candidate:
        candidate = candidate.split("\t", 1)[0].strip()

    if candidate in {"/dev/null", "dev/null"}:
        return None

    if candidate.startswith("a/") or candidate.startswith("b/"):
        candidate = candidate[2:]

    if candidate in {"/dev/null", "dev/null", ""}:
        return None
    return candidate


@dataclass
class ApplyPatchTool:
    root_dir: Path
    timeout_seconds: int = 20
    max_patch_chars: int = 200000

    name: str = "apply_patch"
    description: str = "Apply a unified diff patch inside workspace root"
    permission_level: PermissionLevel = PermissionLevel.L1_WRITE

    @staticmethod
    def _extract_patch_summary(patch_text: str) -> tuple[set[str], int, int]:
        files: set[str] = set()
        hunks = 0
        strip_level = 0

        for line in patch_text.splitlines():
            if line.startswith("@@"):
                hunks += 1
            if line.startswith("--- a/") or line.startswith("+++ b/"):
                strip_level = 1
            if line.startswith(("--- ", "+++ ")):
                normalized = _normalize_patch_path(line[4:])
                if normalized is not None:
                    files.add(normalized)
        return files, hunks, strip_level

    def _run_patch_command(
        self, *, patch_binary: str, patch_text: str, dry_run: bool, strip_level: int
    ) -> tuple[int, str]:
        cmd = [
            patch_binary,
            f"-p{strip_level}",
            "--directory",
            str(self.root_dir),
            "--batch",
            "--forward",
            "--silent",
        ]
        if dry_run:
            cmd.append("--dry-run")
        completed = subprocess.run(
            cmd,
            input=patch_text,
            capture_output=True,
            text=True,
            timeout=self.timeout_seconds,
            check=False,
        )
        output = "\n".join(
            part for part in [completed.stdout, completed.stderr] if part
        ).strip()
        return completed.returncode, output

    def run(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        _ = context
        started = time.monotonic()
        patch_text = str(args.get("input", args.get("patch", "")))
        if not patch_text.strip():
            return ToolResult.failure(
                tool_name=self.name,
                code="E_INVALID_ARGS",
                message="Missing required 'input' argument",
                duration_ms=int((time.monotonic() - started) * 1000),
            )

        if len(patch_text) > self.max_patch_chars:
            return ToolResult.failure(
                tool_name=self.name,
                code="E_INVALID_ARGS",
                message=f"Patch input exceeds max size of {self.max_patch_chars} chars",
                duration_ms=int((time.monotonic() - started) * 1000),
            )

        files, hunks, strip_level = self._extract_patch_summary(patch_text)
        if not files:
            return ToolResult.failure(
                tool_name=self.name,
                code="E_INVALID_ARGS",
                message="Patch does not target any files",
                duration_ms=int((time.monotonic() - started) * 1000),
            )

        for path in sorted(files):
            try:
                resolve_workspace_path(self.root_dir, path)
            except InvalidPathError as exc:
                return ToolResult.failure(
                    tool_name=self.name,
                    code="E_INVALID_PATH",
                    message=str(exc),
                    duration_ms=int((time.monotonic() - started) * 1000),
                    details={"path": path},
                )

        patch_binary = shutil.which("patch")
        if patch_binary is None:
            return ToolResult.failure(
                tool_name=self.name,
                code="E_EXEC",
                message="System 'patch' command is not available",
                duration_ms=int((time.monotonic() - started) * 1000),
            )

        try:
            check_code, check_output = self._run_patch_command(
                patch_binary=patch_binary,
                patch_text=patch_text,
                dry_run=True,
                strip_level=strip_level,
            )
            if check_code != 0:
                return ToolResult.failure(
                    tool_name=self.name,
                    code="E_EXEC",
                    message="Patch check failed",
                    duration_ms=int((time.monotonic() - started) * 1000),
                    details={"output": check_output},
                )

            apply_code, apply_output = self._run_patch_command(
                patch_binary=patch_binary,
                patch_text=patch_text,
                dry_run=False,
                strip_level=strip_level,
            )
            if apply_code != 0:
                return ToolResult.failure(
                    tool_name=self.name,
                    code="E_EXEC",
                    message="Patch apply failed",
                    duration_ms=int((time.monotonic() - started) * 1000),
                    details={"output": apply_output},
                )
        except subprocess.TimeoutExpired:
            return ToolResult.failure(
                tool_name=self.name,
                code="E_TIMEOUT",
                message=f"Patch command timed out after {self.timeout_seconds}s",
                duration_ms=int((time.monotonic() - started) * 1000),
                retryable=True,
            )
        except OSError as exc:
            return ToolResult.failure(
                tool_name=self.name,
                code="E_IO",
                message="Failed to execute patch command",
                duration_ms=int((time.monotonic() - started) * 1000),
                details={"exception": str(exc)},
            )

        return ToolResult.success(
            tool_name=self.name,
            data={
                "applied": True,
                "changed_files": sorted(files),
                "hunks_applied": hunks,
                "errors": [],
            },
            duration_ms=int((time.monotonic() - started) * 1000),
        )
