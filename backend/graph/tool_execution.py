from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

from config import RuntimeConfig
from graph.runtime_types import ToolExecutionEnvelope
from storage.run_store import AuditStore
from tools import (
    get_all_tools,
    get_explicit_blocked_tools,
    get_explicit_enabled_tools,
    get_tool_runner,
)
from tools.base import ToolContext
from tools.contracts import ToolResult
from tools.contracts import ErrorCode
from tools.langchain_tools import build_langchain_tools

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


@dataclass
class ToolExecutionService:
    tools: list[Any]
    tools_by_name: dict[str, Any]

    @classmethod
    def build(
        cls,
        *,
        config_base_dir: Path,
        runtime_root: Path,
        runtime: RuntimeConfig,
        trigger_type: str,
        run_id: str,
        session_id: str,
        runtime_audit_store: AuditStore,
        delegate_tools: list[Any] | None = None,
    ) -> "ToolExecutionService":
        mini_tools = get_all_tools(
            runtime_root,
            runtime,
            trigger_type,
            config_base_dir=config_base_dir,
        )
        explicit_enabled_tools = get_explicit_enabled_tools(runtime, trigger_type)
        explicit_blocked_tools = get_explicit_blocked_tools(runtime, trigger_type)
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
                explicit_enabled_tools=tuple(explicit_enabled_tools),
                explicit_blocked_tools=tuple(explicit_blocked_tools),
                run_id=run_id,
                session_id=session_id,
            ),
            delegate_tools=delegate_tools,
        )
        return cls(
            tools=langchain_tools,
            tools_by_name={tool.name: tool for tool in langchain_tools},
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

            raw_output = await tool.ainvoke(parsed_args)
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
