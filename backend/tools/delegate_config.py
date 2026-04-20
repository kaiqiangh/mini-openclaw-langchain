from __future__ import annotations
from typing import Any

from config import DEFAULT_DELEGATION_CONFIG

ALL_KNOWN_TOOLS = {
    "web_search", "fetch_url", "read_files", "read_pdf", "search_knowledge_base",
    "terminal", "python_repl", "sessions_list", "session_history", "agents_list",
    "scheduler_cron_jobs", "scheduler_cron_runs",
    "scheduler_heartbeat_status", "scheduler_heartbeat_runs", "apply_patch",
}

DELEGATE_DEFAULTS: dict[str, Any] = {
    **DEFAULT_DELEGATION_CONFIG,
    "allowed_tool_scopes": {
        role: list(tools)
        for role, tools in DEFAULT_DELEGATION_CONFIG["allowed_tool_scopes"].items()
    },
}


def validate_delegate_config(config: dict[str, Any]) -> list[str] | None:
    errors: list[str] = []

    max_per = config.get("max_per_session", 5)
    if not isinstance(max_per, int) or max_per < 1:
        errors.append("max_per_session must be >= 1")

    default_timeout = config.get("default_timeout_seconds", 120)
    if not isinstance(default_timeout, int) or default_timeout < 1:
        errors.append("default_timeout_seconds must be >= 1")

    max_timeout = config.get("max_timeout_seconds", 600)
    if not isinstance(max_timeout, int) or max_timeout < 1:
        errors.append("max_timeout_seconds must be >= 1")

    if (isinstance(default_timeout, int) and isinstance(max_timeout, int)
            and default_timeout > max_timeout):
        errors.append("default_timeout_seconds must be <= max_timeout_seconds")

    scopes = config.get("allowed_tool_scopes", {})
    if not isinstance(scopes, dict) or not scopes:
        errors.append("allowed_tool_scopes must be a non-empty dict")
    else:
        for role, tools in scopes.items():
            if not isinstance(tools, list) or not tools:
                errors.append(f"scope '{role}' must be a non-empty list")
            if "delegate" in tools:
                errors.append(f"scope '{role}' cannot include 'delegate' (nested delegation blocked)")

    return errors if errors else None
