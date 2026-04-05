"""Hook types and data models for the HookEngine."""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class HookType(str, Enum):
    PRE_PROMPT_SUBMIT = "pre_prompt_submit"
    PRE_TOOL_USE = "pre_tool_use"
    POST_TOOL_USE = "post_tool_use"
    PRE_COMPACT = "pre_compact"
    STOP = "stop"
    PRE_RUN = "pre_run"


# Which hooks are sync (blocking) vs async (fire-and-forget) by default
_HOOK_SYNC_MAP: dict[HookType, str] = {
    HookType.PRE_PROMPT_SUBMIT: "sync",
    HookType.PRE_TOOL_USE: "sync",
    HookType.POST_TOOL_USE: "async",
    HookType.PRE_COMPACT: "sync",
    HookType.STOP: "async",
    HookType.PRE_RUN: "sync",
}

# Which hooks support veto (deny)
_HOOK_CAN_VETO: dict[HookType, bool] = {
    HookType.PRE_PROMPT_SUBMIT: True,
    HookType.PRE_TOOL_USE: True,
    HookType.POST_TOOL_USE: False,
    HookType.PRE_COMPACT: True,
    HookType.STOP: False,
    HookType.PRE_RUN: True,
}


class HookEvent(BaseModel):
    model_config = {"frozen": False}

    hook_type: str
    agent_id: str
    session_id: str | None = None
    run_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: str = ""


class HookResult(BaseModel):
    allow: bool = True
    reason: str = ""
    modifications: dict[str, Any] = Field(default_factory=dict)


class HookConfig(BaseModel):
    id: str
    type: HookType
    handler: str  # relative path from workspace root
    mode: str = ""  # "sync" | "async" (empty = auto-detect by type)
    timeout_ms: int = 10000

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HookConfig":
        hook_type_str = data["type"]
        hook_type = HookType(hook_type_str)
        mode = data.get("mode", "").strip() or _HOOK_SYNC_MAP.get(hook_type, "async")
        return cls(
            id=data["id"],
            type=hook_type,
            handler=data["handler"],
            mode=mode,
            timeout_ms=int(data.get("timeout_ms", 10000)),
        )

    @property
    def is_sync(self) -> bool:
        return self.mode == "sync"

    def can_veto(self) -> bool:
        return _HOOK_CAN_VETO.get(self.type, False)
