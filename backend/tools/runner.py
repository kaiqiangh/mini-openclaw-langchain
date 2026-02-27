from __future__ import annotations

import time
from typing import Any
from pathlib import Path

from storage.run_store import AuditStore
from .base import MiniTool, ToolContext
from .contracts import ToolResult
from .policy import ToolPolicyEngine
from utils.redaction import redact_json_line


class ToolRunner:
    def __init__(
        self,
        policy_engine: ToolPolicyEngine,
        audit_file: Path | None = None,
        audit_store: AuditStore | None = None,
    ) -> None:
        self.policy_engine = policy_engine
        self.audit_file = audit_file
        self.audit_store = audit_store

    def _write_audit(self, payload: dict[str, Any]) -> None:
        if self.audit_file is None:
            return
        self.audit_file.parent.mkdir(parents=True, exist_ok=True)
        with self.audit_file.open("a", encoding="utf-8") as fh:
            fh.write(redact_json_line(payload) + "\n")

    def run_tool(
        self,
        tool: MiniTool,
        *,
        args: dict[str, Any],
        context: ToolContext,
        explicit_enabled_tools: list[str] | None = None,
    ) -> ToolResult:
        effective_enabled_tools = explicit_enabled_tools
        if effective_enabled_tools is None and context.explicit_enabled_tools:
            effective_enabled_tools = list(context.explicit_enabled_tools)

        started = time.monotonic()
        self._write_audit(
            {
                "event": "tool_start",
                "tool": tool.name,
                "run_id": context.run_id,
                "session_id": context.session_id,
                "trigger_type": context.trigger_type,
                "args": args,
                "timestamp_ms": int(time.time() * 1000),
            }
        )

        decision = self.policy_engine.is_allowed(
            tool_name=tool.name,
            permission_level=tool.permission_level,
            trigger_type=context.trigger_type,
            explicit_enabled_tools=effective_enabled_tools,
        )
        if not decision.allowed:
            duration_ms = int((time.monotonic() - started) * 1000)
            self._write_audit(
                {
                    "event": "tool_end",
                    "tool": tool.name,
                    "run_id": context.run_id,
                    "session_id": context.session_id,
                    "trigger_type": context.trigger_type,
                    "duration_ms": duration_ms,
                    "ok": False,
                    "policy_decision": "denied",
                    "reason": decision.reason,
                    "timestamp_ms": int(time.time() * 1000),
                }
            )
            if self.audit_store is not None:
                self.audit_store.append_tool_call(
                    run_id=context.run_id,
                    session_id=context.session_id,
                    trigger_type=context.trigger_type,
                    tool_name=tool.name,
                    status="denied",
                    duration_ms=duration_ms,
                    details={"reason": decision.reason},
                )
            return ToolResult.failure(
                tool_name=tool.name,
                code="E_POLICY_DENIED",
                message=decision.reason,
                duration_ms=duration_ms,
                retryable=False,
            )

        try:
            result = tool.run(args, context)
            self._write_audit(
                {
                    "event": "tool_end",
                    "tool": tool.name,
                    "run_id": context.run_id,
                    "session_id": context.session_id,
                    "trigger_type": context.trigger_type,
                    "duration_ms": result.meta.duration_ms,
                    "ok": result.ok,
                    "policy_decision": "allowed",
                    "timestamp_ms": int(time.time() * 1000),
                }
            )
            if self.audit_store is not None:
                self.audit_store.append_tool_call(
                    run_id=context.run_id,
                    session_id=context.session_id,
                    trigger_type=context.trigger_type,
                    tool_name=tool.name,
                    status="ok" if result.ok else "error",
                    duration_ms=result.meta.duration_ms,
                    details={"truncated": result.meta.truncated},
                )
            return result
        except Exception as exc:  # noqa: BLE001
            duration_ms = int((time.monotonic() - started) * 1000)
            self._write_audit(
                {
                    "event": "tool_end",
                    "tool": tool.name,
                    "run_id": context.run_id,
                    "session_id": context.session_id,
                    "trigger_type": context.trigger_type,
                    "duration_ms": duration_ms,
                    "ok": False,
                    "policy_decision": "allowed",
                    "error": str(exc),
                    "timestamp_ms": int(time.time() * 1000),
                }
            )
            if self.audit_store is not None:
                self.audit_store.append_tool_call(
                    run_id=context.run_id,
                    session_id=context.session_id,
                    trigger_type=context.trigger_type,
                    tool_name=tool.name,
                    status="error",
                    duration_ms=duration_ms,
                    details={"exception": str(exc)},
                )
            return ToolResult.failure(
                tool_name=tool.name,
                code="E_INTERNAL",
                message="Unhandled tool exception",
                duration_ms=duration_ms,
                retryable=False,
                details={"exception": str(exc)},
            )
