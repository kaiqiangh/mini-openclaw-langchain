"""Docker-based sandbox executor with fallback to in-process execution."""
from __future__ import annotations

import json
import subprocess
import shutil
import logging
from dataclasses import dataclass
from typing import Any

from .python_repl_tool import _execute_python_snippet, _contains_escape_attempt, _get_mp_context

logger = logging.getLogger(__name__)

SANDBOX_IMAGE = "python-repl-sandbox:latest"


@dataclass
class SandboxConfig:
    mode: str = "in_process"  # "in_process" | "docker" | "auto"
    image: str = SANDBOX_IMAGE
    memory: str = "256m"
    cpus: str = "1"
    timeout_seconds: int = 30

    @classmethod
    def from_env(cls) -> SandboxConfig:
        import os

        mode = os.environ.get("REPL_SANDBOX_MODE", "in_process").strip().lower()
        image = os.environ.get("REPL_SANDBOX_IMAGE", SANDBOX_IMAGE)
        return cls(mode=mode, image=image)


def _docker_available(image: str) -> bool:
    """Check if Docker is available and the sandbox image exists."""
    if not shutil.which("docker"):
        return False
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", image],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def _run_in_docker(code: str, config: SandboxConfig) -> dict[str, Any]:
    """Execute code in a Docker container, return JSON result."""
    cmd = [
        "docker", "run", "--rm", "-i",
        f"--memory={config.memory}",
        f"--cpus={config.cpus}",
        "--network=none",
        "--read-only",
        "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
        "--pids-limit", "64",
        "--security-opt", "no-new-privileges:true",
        "--cap-drop", "ALL",
        config.image,
    ]
    try:
        result = subprocess.run(
            cmd,
            input=code.encode(),
            capture_output=True,
            timeout=config.timeout_seconds,
        )
        if result.returncode == 0 or result.stdout:
            try:
                return json.loads(result.stdout.decode())
            except json.JSONDecodeError:
                return {
                    "ok": False,
                    "error": f"Invalid sandbox output: {result.stdout.decode()[:200]}",
                }
        error_msg = result.stderr.decode()[:500] if result.stderr else "Unknown Docker error"
        return {"ok": False, "error": f"Docker execution failed: {error_msg}"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"Docker execution timed out after {config.timeout_seconds}s"}
    except Exception as exc:
        return {"ok": False, "error": f"Docker execution error: {exc}"}


def _run_in_process(code: str, timeout_seconds: int = 30) -> dict[str, Any]:
    """Execute code in-process via multiprocessing (existing logic)."""
    if _contains_escape_attempt(code):
        return {"ok": False, "error": "Code contains disallowed patterns (introspection/escape)"}

    ctx = _get_mp_context()
    recv_conn, send_conn = ctx.Pipe(duplex=False)
    process = ctx.Process(target=_execute_python_snippet, args=(code, send_conn))
    process.start()
    send_conn.close()
    process.join(timeout=timeout_seconds)

    if process.is_alive():
        process.terminate()
        process.join()
        recv_conn.close()
        return {"ok": False, "error": f"Python execution timed out after {timeout_seconds}s"}

    try:
        if recv_conn.poll():
            return recv_conn.recv()
        return {"ok": False, "error": "No output from Python process"}
    except Exception:
        return {"ok": False, "error": "No output from Python process"}
    finally:
        recv_conn.close()


class SandboxExecutor:
    """Unified executor: Docker sandbox with in-process fallback."""

    def __init__(self, config: SandboxConfig | None = None):
        self.config = config or SandboxConfig.from_env()
        self._docker_usable: bool | None = None

    @property
    def use_docker(self) -> bool:
        if self.config.mode == "in_process":
            return False
        if self.config.mode == "docker":
            return True
        # "auto" mode
        if self._docker_usable is None:
            self._docker_usable = _docker_available(self.config.image)
        return self._docker_usable

    def run(self, code: str) -> dict[str, Any]:
        if self.use_docker:
            logger.debug("Executing via Docker sandbox")
            result = _run_in_docker(code, self.config)
            if not result["ok"] and "Docker execution error" in result.get("error", ""):
                logger.warning(
                    "Docker execution failed, falling back to in-process: %s",
                    result["error"],
                )
                return _run_in_process(code, self.config.timeout_seconds)
            return result
        else:
            logger.debug("Executing via in-process sandbox")
            return _run_in_process(code, self.config.timeout_seconds)
