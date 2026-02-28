from __future__ import annotations

import pytest

from config import RuntimeConfig
from tools import get_explicit_enabled_tools
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


def test_cron_tools_fallback_when_agent_config_is_empty():
    runtime = RuntimeConfig()
    runtime.autonomous_tools.cron_enabled_tools = []
    assert get_explicit_enabled_tools(runtime, "cron") == [
        "web_search",
        "web_fetch",
        "fetch_url",
        "read",
        "read_file",
        "read_files",
        "search_knowledge_base",
    ]
