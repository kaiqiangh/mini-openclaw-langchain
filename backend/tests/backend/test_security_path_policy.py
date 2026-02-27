from __future__ import annotations

import pytest

from tools.path_guard import InvalidPathError, resolve_workspace_path
from tools.policy import PermissionLevel, ToolPolicyEngine


def test_path_guard_rejects_absolute_and_parent_paths(tmp_path):
    with pytest.raises(InvalidPathError):
        resolve_workspace_path(tmp_path, "/etc/passwd")

    with pytest.raises(InvalidPathError):
        resolve_workspace_path(tmp_path, "../escape.txt")


def test_autonomous_policy_defaults_to_low_authority():
    policy = ToolPolicyEngine()

    denied = policy.is_allowed(
        tool_name="terminal",
        permission_level=PermissionLevel.L3_SYSTEM,
        trigger_type="heartbeat",
    )
    assert denied.allowed is False

    allowed = policy.is_allowed(
        tool_name="terminal",
        permission_level=PermissionLevel.L3_SYSTEM,
        trigger_type="heartbeat",
        explicit_enabled_tools=["terminal"],
    )
    assert allowed.allowed is True
