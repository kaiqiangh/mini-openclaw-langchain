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


def test_chat_terminal_requires_explicit_enable():
    policy = ToolPolicyEngine()

    denied = policy.is_allowed(
        tool_name="terminal",
        permission_level=PermissionLevel.L3_SYSTEM,
        trigger_type="chat",
    )
    assert denied.allowed is False
    assert "requires explicit enable" in denied.reason

    allowed = policy.is_allowed(
        tool_name="terminal",
        permission_level=PermissionLevel.L3_SYSTEM,
        trigger_type="chat",
        explicit_enabled_tools=["terminal"],
    )
    assert allowed.allowed is True


def test_cron_tools_fallback_when_agent_config_is_empty():
    runtime = RuntimeConfig()
    runtime.autonomous_tools.cron_enabled_tools = []
    assert get_explicit_enabled_tools(runtime, "cron") == [
        "web_search",
        "fetch_url",
        "read_files",
        "read_pdf",
        "search_knowledge_base",
        "sessions_list",
        "session_history",
        "agents_list",
        "scheduler_cron_jobs",
        "scheduler_cron_runs",
        "scheduler_heartbeat_status",
        "scheduler_heartbeat_runs",
    ]


def test_chat_explicit_tools_are_agent_scoped():
    runtime = RuntimeConfig()
    runtime.chat_enabled_tools = ["terminal"]
    assert get_explicit_enabled_tools(runtime, "chat") == ["terminal"]


def test_chat_explicit_high_risk_tools_do_not_block_low_risk_tools():
    policy = ToolPolicyEngine()
    allowed = policy.is_allowed(
        tool_name="read_files",
        permission_level=PermissionLevel.L0_READ,
        trigger_type="chat",
        explicit_enabled_tools=["terminal"],
    )
    assert allowed.allowed is True
