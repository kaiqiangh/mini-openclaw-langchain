from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


ErrorCode = Literal[
    "E_POLICY_DENIED",
    "E_INVALID_ARGS",
    "E_NOT_FOUND",
    "E_INVALID_PATH",
    "E_IO",
    "E_TIMEOUT",
    "E_HTTP",
    "E_EXEC",
    "E_INTERNAL",
]


@dataclass
class ToolError:
    code: ErrorCode
    message: str
    retryable: bool = False
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolMeta:
    tool_name: str
    duration_ms: int
    truncated: bool = False
    warnings: list[str] = field(default_factory=list)


@dataclass
class ToolResult:
    ok: bool
    data: dict[str, Any]
    meta: ToolMeta
    error: ToolError | None = None

    @staticmethod
    def success(
        tool_name: str,
        data: dict[str, Any],
        duration_ms: int,
        truncated: bool = False,
        warnings: list[str] | None = None,
    ) -> "ToolResult":
        return ToolResult(
            ok=True,
            data=data,
            meta=ToolMeta(
                tool_name=tool_name,
                duration_ms=duration_ms,
                truncated=truncated,
                warnings=warnings or [],
            ),
            error=None,
        )

    @staticmethod
    def failure(
        tool_name: str,
        code: ErrorCode,
        message: str,
        duration_ms: int,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> "ToolResult":
        return ToolResult(
            ok=False,
            data={},
            meta=ToolMeta(tool_name=tool_name, duration_ms=duration_ms),
            error=ToolError(
                code=code,
                message=message,
                retryable=retryable,
                details=details or {},
            ),
        )
