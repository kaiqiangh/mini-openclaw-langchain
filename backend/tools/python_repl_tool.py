from __future__ import annotations

import __main__
import io
import multiprocessing as mp
import os
import resource
import sys
import time
from contextlib import redirect_stdout
from dataclasses import dataclass
from typing import Any

from .base import ToolContext
from .contracts import ToolResult
from .policy import PermissionLevel

_ESCAPE_PATTERNS = (
    "__class__",
    "__bases__",
    "__subclasses__",
    "__mro__",
    "__import__",
    "__builtins__",
    "getattr(",
    "setattr(",
    "delattr(",
    "globals()",
    "locals()",
    "vars()",
    "dir()",
    "open(",
    "compile(",
    "eval(",
    "exec(",
)


def _contains_escape_attempt(code: str) -> bool:
    lowered = code.lower()
    return any(pattern in lowered for pattern in _ESCAPE_PATTERNS)


def _set_resource_limits(timeout_seconds: int) -> None:
    try:
        resource.setrlimit(resource.RLIMIT_CPU, (timeout_seconds, timeout_seconds))
    except (ValueError, resource.error):
        pass
    try:
        mem_limit = 256 * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (mem_limit, mem_limit))
    except (ValueError, resource.error):
        pass
    try:
        resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))
    except (ValueError, resource.error):
        pass
    try:
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    except (ValueError, resource.error):
        pass


def _main_module_supports_spawn() -> bool:
    main_file = getattr(__main__, "__file__", None)
    if not main_file or str(main_file).startswith("<"):
        return False
    return os.path.exists(main_file)


def _get_mp_context() -> mp.context.BaseContext:
    methods = set(mp.get_all_start_methods())
    if sys.platform.startswith("linux") and "forkserver" in methods and _main_module_supports_spawn():
        return mp.get_context("forkserver")
    if "spawn" in methods and _main_module_supports_spawn():
        return mp.get_context("spawn")
    if "fork" in methods:
        return mp.get_context("fork")
    return mp.get_context()


def _execute_python_snippet(code: str, conn: Any) -> None:
    payload: dict[str, Any]
    if _contains_escape_attempt(code):
        payload = {"ok": False, "error": "Code contains disallowed patterns (introspection/escape)"}
        conn.send(payload)
        conn.close()
        return

    try:
        _set_resource_limits(30)
    except Exception:
        pass

    safe_globals = {
        "__builtins__": {
            "abs": abs,
            "all": all,
            "any": any,
            "bool": bool,
            "dict": dict,
            "enumerate": enumerate,
            "filter": filter,
            "float": float,
            "format": format,
            "frozenset": frozenset,
            "int": int,
            "isinstance": isinstance,
            "issubclass": issubclass,
            "len": len,
            "list": list,
            "map": map,
            "max": max,
            "min": min,
            "print": print,
            "range": range,
            "reversed": reversed,
            "round": round,
            "set": set,
            "sorted": sorted,
            "str": str,
            "sum": sum,
            "tuple": tuple,
            "type": type,
            "zip": zip,
        }
    }
    safe_locals: dict[str, Any] = {}
    buffer = io.StringIO()
    try:
        with redirect_stdout(buffer):
            exec(code, safe_globals, safe_locals)
    except Exception as exc:  # noqa: BLE001
        payload = {"ok": False, "error": str(exc)}
        conn.send(payload)
        conn.close()
        return
    payload = {"ok": True, "output": buffer.getvalue().strip()}
    conn.send(payload)
    conn.close()


@dataclass
class PythonReplTool:
    timeout_seconds: int = 30
    output_char_limit: int = 5000
    use_sandbox: bool = False

    name: str = "python_repl"
    description: str = "Execute Python snippets in constrained REPL scope"
    permission_level: PermissionLevel = PermissionLevel.L1_WRITE

    def __post_init__(self):
        import os
        mode = os.environ.get("REPL_SANDBOX_MODE", "in_process").lower()
        self.use_sandbox = mode in ("docker", "auto")
        self._executor = None

    def _get_executor(self):
        if self._executor is None:
            from .sandbox_executor import SandboxExecutor, SandboxConfig
            self._executor = SandboxExecutor(SandboxConfig.from_env())
        return self._executor

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

        if self.use_sandbox:
            executor = self._get_executor()
            payload = executor.run(code)
        else:
            ctx = _get_mp_context()
            recv_conn, send_conn = ctx.Pipe(duplex=False)
            process = ctx.Process(target=_execute_python_snippet, args=(code, send_conn))
            process.start()
            send_conn.close()
            process.join(timeout=self.timeout_seconds)

            if process.is_alive():
                process.terminate()
                process.join()
                recv_conn.close()
                return ToolResult.failure(
                    tool_name=self.name,
                    code="E_TIMEOUT",
                    message=f"Python execution timed out after {self.timeout_seconds}s",
                    duration_ms=int((time.monotonic() - started) * 1000),
                    retryable=True,
                )

            payload: dict[str, Any] = {"ok": False, "error": "No output from Python process"}
            try:
                if recv_conn.poll():
                    payload = recv_conn.recv()
            except Exception:
                payload = {"ok": False, "error": "No output from Python process"}
            finally:
                recv_conn.close()

        if not payload.get("ok"):
            return ToolResult.failure(
                tool_name=self.name,
                code="E_EXEC",
                message="Python execution failed",
                duration_ms=int((time.monotonic() - started) * 1000),
                details={"exception": str(payload.get("error", "unknown"))},
            )

        output = str(payload.get("output", ""))
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
