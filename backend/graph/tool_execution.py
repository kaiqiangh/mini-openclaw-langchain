from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from config import RuntimeConfig
from graph.runtime_types import ToolExecutionEnvelope
from storage.run_store import AuditStore
from tools import (
    get_all_tools,
    get_all_declared_tools,
    get_explicit_blocked_tools,
    get_explicit_enabled_tools,
    get_tool_runner,
)
from tools.base import ToolContext
from tools.contracts import ToolResult
from tools.contracts import ErrorCode
from tools.langchain_tools import build_langchain_tools
from hooks.engine import HookEngine
from hooks.types import HookEvent

_ERROR_CODES: tuple[ErrorCode, ...] = (
    "E_POLICY_DENIED",
    "E_INVALID_ARGS",
    "E_NOT_FOUND",
    "E_INVALID_PATH",
    "E_IO",
    "E_TIMEOUT",
    "E_HTTP",
    "E_EXEC",
    "E_SANDBOX_UNAVAILABLE",
    "E_SANDBOX_REQUIRED",
    "E_INTERNAL",
)


def _normalize_error_code(value: Any) -> ErrorCode | None:
    code = str(value or "").strip()
    if code in _ERROR_CODES:
        return cast(ErrorCode, code)
    return None


def _failure_payload(
    *,
    tool_name: str,
    message: str,
    duration_ms: int = 0,
    code: ErrorCode = "E_NOT_FOUND",
) -> str:
    return json.dumps(
        asdict(
            ToolResult.failure(
                tool_name=tool_name,
                code=code,
                message=message,
                duration_ms=duration_ms,
                retryable=False,
            )
        ),
        ensure_ascii=False,
    )


def _hook_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ToolExecutionService:
    tools: list[Any]
    tools_by_name: dict[str, Any]
    hook_engine: HookEngine | None = None
    audit_store: AuditStore | None = None
    trigger_type: str = "chat"
    agent_id: str = "default"
    run_id: str = ""
    session_id: str = ""

    @classmethod
    def build(
        cls,
        *,
        config_base_dir: Path,
        runtime_root: Path,
        runtime: RuntimeConfig,
        trigger_type: str,
        agent_id: str,
        run_id: str,
        session_id: str,
        runtime_audit_store: AuditStore,
        delegate_tools: list[Any] | None = None,
        hook_engine: HookEngine | None = None,
        explicit_enabled_tools: list[str] | None = None,
        explicit_blocked_tools: list[str] | None = None,
    ) -> "ToolExecutionService":
        runtime_enabled_tools = get_explicit_enabled_tools(runtime, trigger_type)
        runtime_blocked_tools = get_explicit_blocked_tools(runtime, trigger_type)
        effective_enabled_tools = (
            list(explicit_enabled_tools)
            if explicit_enabled_tools is not None
            else list(runtime_enabled_tools)
        )
        effective_blocked_tools = (
            list(explicit_blocked_tools)
            if explicit_blocked_tools is not None
            else list(runtime_blocked_tools)
        )
        if explicit_enabled_tools is not None or explicit_blocked_tools is not None:
            declared_tools = get_all_declared_tools(
                runtime_root,
                runtime,
                config_base_dir=config_base_dir,
            )
            mini_tools = [
                tool
                for tool in declared_tools
                if (
                    tool.name not in effective_blocked_tools
                    and (
                        explicit_enabled_tools is None
                        or tool.name in effective_enabled_tools
                    )
                )
            ]
        else:
            mini_tools = get_all_tools(
                runtime_root,
                runtime,
                trigger_type,
                config_base_dir=config_base_dir,
            )
        runner = get_tool_runner(
            runtime_root,
            runtime_audit_store,
            repeat_identical_failure_limit=runtime.tool_retry_guard.repeat_identical_failure_limit,
        )
        langchain_tools = build_langchain_tools(
            tools=mini_tools,
            runner=runner,
            context=ToolContext(
                workspace_root=runtime_root,
                trigger_type=trigger_type,
                agent_id=agent_id,
                explicit_enabled_tools=tuple(effective_enabled_tools),
                explicit_blocked_tools=tuple(effective_blocked_tools),
                run_id=run_id,
                session_id=session_id,
            ),
            delegate_tools=delegate_tools,
        )
        return cls(
            tools=langchain_tools,
            tools_by_name={tool.name: tool for tool in langchain_tools},
            hook_engine=hook_engine,
            audit_store=runtime_audit_store,
            trigger_type=trigger_type,
            agent_id=agent_id,
            run_id=run_id,
            session_id=session_id,
        )

    def _append_hook_audit_event(
        self,
        *,
        hook_event: HookEvent,
        hook_type: str,
        status: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        if self.audit_store is None:
            return
        self.audit_store.append_step(
            agent_id=self.agent_id,
            run_id=self.run_id,
            session_id=self.session_id,
            trigger_type=self.trigger_type,
            event=f"hook_{hook_type}",
            hook_type=hook_type,
            status=status,
            details={
                "session_id": hook_event.session_id or self.session_id,
                "run_id": hook_event.run_id or self.run_id,
                "timestamp": hook_event.timestamp,
                **(details or {}),
            },
        )

    async def execute_pending(
        self,
        tool_calls: list[dict[str, Any]],
    ) -> tuple[list[ToolExecutionEnvelope], list[Any]]:
        from langchain_core.messages import ToolMessage

        envelopes: list[ToolExecutionEnvelope] = []
        tool_messages: list[Any] = []

        for index, call in enumerate(tool_calls):
            tool_name = str(call.get("name", "unknown")).strip() or "unknown"
            tool_call_id = (
                str(call.get("id", "")).strip()
                or str(call.get("tool_call_id", "")).strip()
                or f"{tool_name}-{index}"
            )
            args = call.get("args", {})
            parsed_args = args if isinstance(args, dict) else {}
            tool = self.tools_by_name.get(tool_name)

            if tool is None:
                raw_output = _failure_payload(
                    tool_name=tool_name,
                    message=f"Tool '{tool_name}' is not available",
                )
                envelopes.append(
                    ToolExecutionEnvelope(
                        tool=tool_name,
                        tool_call_id=tool_call_id,
                        args=parsed_args,
                        output=raw_output,
                        raw_output=raw_output,
                        ok=False,
                        duration_ms=0,
                        error_code="E_NOT_FOUND",
                        error_message=f"Tool '{tool_name}' is not available",
                    )
                )
                tool_messages.append(
                    ToolMessage(
                        content=raw_output,
                        name=tool_name,
                        tool_call_id=tool_call_id,
                        status="error",
                    )
                )
                continue

            # PreToolUse hook (sync, can veto)
            if self.hook_engine and self.hook_engine.is_enabled:
                hook_event = HookEvent(
                    hook_type="pre_tool_use",
                    agent_id=self.agent_id,
                    session_id=self.session_id,
                    run_id=self.run_id,
                    timestamp=_hook_timestamp(),
                    payload={"tool_name": tool_name, "input": parsed_args},
                )
                hook_result = self.hook_engine.dispatch_sync(hook_event)
                self._append_hook_audit_event(
                    hook_event=hook_event,
                    hook_type="pre_tool_use",
                    status="allow" if hook_result.allow else "deny",
                    details={
                        "tool_name": tool_name,
                        "input": parsed_args,
                        "reason": hook_result.reason,
                    },
                )
                if not hook_result.allow:
                    raw_output = _failure_payload(
                        tool_name=tool_name,
                        message=f"Hook denied: {hook_result.reason}",
                        code="E_POLICY_DENIED",
                    )
                    envelopes.append(
                        ToolExecutionEnvelope(
                            tool=tool_name,
                            tool_call_id=tool_call_id,
                            args=parsed_args,
                            output=raw_output,
                            raw_output=raw_output,
                            ok=False,
                            duration_ms=0,
                            error_code="E_POLICY_DENIED",
                            error_message=f"Hook denied: {hook_result.reason}",
                        )
                    )
                    tool_messages.append(
                        ToolMessage(
                            content=raw_output,
                            name=tool_name,
                            tool_call_id=tool_call_id,
                            status="error",
                        )
                    )
                    continue

            raw_output = await tool.ainvoke(parsed_args)

            # PostToolUse hook (async, fire-and-forget)
            if self.hook_engine and self.hook_engine.is_enabled:
                hook_event = HookEvent(
                    hook_type="post_tool_use",
                    agent_id=self.agent_id,
                    session_id=self.session_id,
                    run_id=self.run_id,
                    timestamp=_hook_timestamp(),
                    payload={"tool_name": tool_name, "result": str(raw_output)},
                )
                self.hook_engine.dispatch_async(hook_event)
                self._append_hook_audit_event(
                    hook_event=hook_event,
                    hook_type="post_tool_use",
                    status="dispatched",
                    details={
                        "tool_name": tool_name,
                        "result_preview": str(raw_output)[:300],
                    },
                )

            parsed: dict[str, Any] = {}
            if isinstance(raw_output, str):
                try:
                    candidate = json.loads(raw_output)
                    if isinstance(candidate, dict):
                        parsed = candidate
                except json.JSONDecodeError:
                    parsed = {}

            meta = parsed.get("meta", {}) if isinstance(parsed.get("meta"), dict) else {}
            error = (
                parsed.get("error", {}) if isinstance(parsed.get("error"), dict) else {}
            )
            ok = bool(parsed.get("ok", False))
            duration_ms = int(meta.get("duration_ms", 0) or 0)
            warnings = meta.get("warnings", [])
            normalized_warnings = (
                [str(item) for item in warnings]
                if isinstance(warnings, list)
                else []
            )
            envelope = ToolExecutionEnvelope(
                tool=tool_name,
                tool_call_id=tool_call_id,
                args=parsed_args,
                output=str(raw_output),
                raw_output=str(raw_output),
                ok=ok,
                duration_ms=duration_ms,
                warnings=normalized_warnings,
                error_code=_normalize_error_code(error.get("code")),
                retryable=bool(error.get("retryable", False)),
                error_message=str(error.get("message", "")).strip() or None,
                details=parsed if parsed else {},
            )
            envelopes.append(envelope)
            tool_messages.append(
                ToolMessage(
                    content=str(raw_output),
                    name=tool_name,
                    tool_call_id=tool_call_id,
                    status="success" if ok else "error",
                )
            )

        return envelopes, tool_messages
