from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Iterable


class PermissionLevel(IntEnum):
    L0_READ = 0
    L1_WRITE = 1
    L2_NETWORK = 2
    L3_SYSTEM = 3


@dataclass
class PolicyDecision:
    allowed: bool
    reason: str


DEFAULT_MAX_LEVEL_BY_TRIGGER: dict[str, PermissionLevel] = {
    "chat": PermissionLevel.L2_NETWORK,
    "heartbeat": PermissionLevel.L0_READ,
    "cron": PermissionLevel.L0_READ,
}

AUTONOMOUS_TRIGGERS = {"heartbeat", "cron"}
CHAT_HIGH_RISK_TOOLS = {"terminal", "exec"}


class ToolPolicyEngine:
    def __init__(self) -> None:
        self.max_level_by_trigger = dict(DEFAULT_MAX_LEVEL_BY_TRIGGER)

    def is_allowed(
        self,
        *,
        tool_name: str,
        permission_level: PermissionLevel,
        trigger_type: str,
        explicit_enabled_tools: Iterable[str] | None = None,
    ) -> PolicyDecision:
        enabled = set(explicit_enabled_tools or [])
        # Autonomous triggers default to least authority; explicit-enabled tools bypass level caps.
        if trigger_type in AUTONOMOUS_TRIGGERS:
            if tool_name in enabled:
                return PolicyDecision(True, "allowed_via_explicit_enable")
        elif trigger_type == "chat" and tool_name in CHAT_HIGH_RISK_TOOLS:
            if tool_name in enabled:
                return PolicyDecision(True, "allowed_via_explicit_enable")
            return PolicyDecision(
                False, f"high risk tool '{tool_name}' requires explicit enable"
            )
        elif trigger_type != "chat" and enabled and tool_name not in enabled:
            return PolicyDecision(
                False, f"tool '{tool_name}' is not in explicit enabled set"
            )

        max_level = self.max_level_by_trigger.get(trigger_type, PermissionLevel.L0_READ)
        if permission_level > max_level:
            return PolicyDecision(
                False,
                f"permission level {permission_level.name} exceeds max {max_level.name} for trigger '{trigger_type}'",
            )

        return PolicyDecision(True, "allowed")
