from __future__ import annotations

from pathlib import Path
from typing import Any

from config import RuntimeConfig
from storage.run_store import AuditStore

from .agents_list_tool import AgentsListTool
from .apply_patch_tool import ApplyPatchTool
from .base import MiniTool
from .fetch_url_tool import FetchUrlTool
from .policy import ToolPolicyEngine
from .python_repl_tool import PythonReplTool
from .read_pdf_tool import ReadPdfTool
from .read_files_tool import ReadFilesTool
from .runner import ToolRunner
from .scheduler_tools import (
    SchedulerCronJobsTool,
    SchedulerCronRunsTool,
    SchedulerHeartbeatRunsTool,
    SchedulerHeartbeatStatusTool,
)
from .search_knowledge_tool import SearchKnowledgeTool
from .session_history_tool import SessionHistoryTool
from .sessions_list_tool import SessionsListTool
from .skills_scanner import ensure_skills_snapshot, scan_skills
from .terminal_tool import TerminalTool
from .web_search_tool import WebSearchTool

TRIGGER_TYPES: tuple[str, ...] = ("chat", "heartbeat", "cron")


def get_explicit_enabled_tools(runtime: RuntimeConfig, trigger_type: str) -> list[str]:
    if trigger_type == "chat":
        return list(runtime.chat_enabled_tools)
    if trigger_type == "heartbeat":
        return list(runtime.autonomous_tools.heartbeat_enabled_tools)
    if trigger_type == "cron":
        return [
            str(name).strip()
            for name in runtime.autonomous_tools.cron_enabled_tools
            if str(name).strip()
        ]
    return []


def get_explicit_blocked_tools(runtime: RuntimeConfig, trigger_type: str) -> list[str]:
    if trigger_type == "chat":
        return list(runtime.chat_blocked_tools)
    return []


def _build_declared_tools(
    base_dir: Path,
    runtime: RuntimeConfig,
    config_base_dir: Path | None = None,
) -> list[MiniTool]:
    terminal_mode = runtime.tool_execution.terminal.sandbox_mode
    terminal_mode_value = (
        terminal_mode.value if hasattr(terminal_mode, "value") else str(terminal_mode)
    )
    terminal_policy_mode = runtime.tool_execution.terminal.command_policy_mode
    terminal_policy_mode_value = (
        terminal_policy_mode.value
        if hasattr(terminal_policy_mode, "value")
        else str(terminal_policy_mode)
    )
    return [
        TerminalTool(
            root_dir=base_dir,
            timeout_seconds=runtime.tool_timeouts.terminal_seconds,
            output_char_limit=runtime.tool_output_limits.terminal_chars,
            sandbox_mode=terminal_mode_value,
            command_policy_mode=terminal_policy_mode_value,
            require_sandbox=runtime.tool_execution.terminal.require_sandbox,
            allowed_command_prefixes=tuple(
                runtime.tool_execution.terminal.allowed_command_prefixes
            ),
            denied_command_prefixes=tuple(
                runtime.tool_execution.terminal.denied_command_prefixes
            ),
            allow_network=runtime.tool_execution.terminal.allow_network,
            allow_shell_syntax=runtime.tool_execution.terminal.allow_shell_syntax,
            max_args=runtime.tool_execution.terminal.max_args,
            max_arg_length=runtime.tool_execution.terminal.max_arg_length,
        ),
        PythonReplTool(
            timeout_seconds=runtime.tool_timeouts.python_repl_seconds,
            output_char_limit=runtime.tool_output_limits.terminal_chars,
        ),
        FetchUrlTool(
            timeout_seconds=runtime.tool_timeouts.fetch_url_seconds,
            output_char_limit=runtime.tool_output_limits.fetch_url_chars,
            allowed_schemes=tuple(runtime.tool_network.allow_http_schemes),
            block_private_networks=runtime.tool_network.block_private_networks,
            max_redirects=runtime.tool_network.max_redirects,
            max_content_bytes=runtime.tool_network.max_content_bytes,
        ),
        ReadFilesTool(
            root_dir=base_dir,
            max_chars_default=runtime.tool_output_limits.read_file_chars,
        ),
        ReadPdfTool(
            root_dir=base_dir,
            max_chars_default=runtime.tool_output_limits.read_file_chars,
        ),
        SearchKnowledgeTool(
            root_dir=base_dir,
            config_base_dir=config_base_dir,
            default_top_k=runtime.retrieval.knowledge.top_k,
            semantic_weight=runtime.retrieval.knowledge.semantic_weight,
            lexical_weight=runtime.retrieval.knowledge.lexical_weight,
            chunk_size=runtime.retrieval.knowledge.chunk_size,
            chunk_overlap=runtime.retrieval.knowledge.chunk_overlap,
        ),
        SessionsListTool(runtime_root=base_dir, config_base_dir=config_base_dir),
        SessionHistoryTool(runtime_root=base_dir, config_base_dir=config_base_dir),
        AgentsListTool(runtime_root=base_dir, config_base_dir=config_base_dir),
        SchedulerCronJobsTool(runtime_root=base_dir, config_base_dir=config_base_dir),
        SchedulerCronRunsTool(runtime_root=base_dir, config_base_dir=config_base_dir),
        SchedulerHeartbeatStatusTool(
            runtime_root=base_dir, config_base_dir=config_base_dir
        ),
        SchedulerHeartbeatRunsTool(
            runtime_root=base_dir, config_base_dir=config_base_dir
        ),
        WebSearchTool(timeout_seconds=runtime.tool_timeouts.fetch_url_seconds),
        ApplyPatchTool(
            root_dir=base_dir, timeout_seconds=runtime.tool_timeouts.terminal_seconds
        ),
    ]


def get_all_declared_tools(
    base_dir: Path,
    runtime: RuntimeConfig,
    config_base_dir: Path | None = None,
) -> list[MiniTool]:
    return _build_declared_tools(
        base_dir,
        runtime,
        config_base_dir=config_base_dir,
    )


def build_tool_catalog(
    base_dir: Path,
    runtime: RuntimeConfig,
    config_base_dir: Path | None = None,
) -> dict[str, Any]:
    policy = ToolPolicyEngine()
    trigger_explicit_tools = {
        trigger: get_explicit_enabled_tools(runtime, trigger) for trigger in TRIGGER_TYPES
    }
    trigger_blocked_tools = {
        trigger: get_explicit_blocked_tools(runtime, trigger)
        for trigger in TRIGGER_TYPES
    }
    trigger_enabled_sets = {
        trigger: set(enabled_tools)
        for trigger, enabled_tools in trigger_explicit_tools.items()
    }
    trigger_blocked_sets = {
        trigger: set(blocked_tools)
        for trigger, blocked_tools in trigger_blocked_tools.items()
    }
    trigger_effective_tools = {trigger: [] for trigger in TRIGGER_TYPES}
    all_tools = _build_declared_tools(
        base_dir,
        runtime,
        config_base_dir=config_base_dir,
    )
    rows: list[dict[str, Any]] = []
    for tool in all_tools:
        trigger_status: dict[str, Any] = {}
        for trigger, enabled_tools in trigger_explicit_tools.items():
            blocked_tools = trigger_blocked_tools[trigger]
            decision = policy.is_allowed(
                tool_name=tool.name,
                permission_level=tool.permission_level,
                trigger_type=trigger,
                explicit_enabled_tools=enabled_tools,
                explicit_blocked_tools=blocked_tools,
            )
            if decision.allowed:
                trigger_effective_tools[trigger].append(tool.name)
            trigger_status[trigger] = {
                "enabled": bool(decision.allowed),
                "explicitly_enabled": tool.name in trigger_enabled_sets[trigger],
                "explicitly_blocked": tool.name in trigger_blocked_sets[trigger],
                "allowed_by_policy": bool(decision.allowed),
                "reason": decision.reason,
            }
        rows.append(
            {
                "name": tool.name,
                "description": tool.description,
                "permission_level": tool.permission_level.name,
                "trigger_status": trigger_status,
            }
        )

    # ── Inject delegation tools (StructuredTools built at runtime, not MiniTools) ──
    _DELEGATE_TOOLS = [
        ("delegate", "Delegate a sub-task to an isolated agent instance with scoped tool access. Runs independently. Use delegate_status to check progress. No nesting."),
        ("delegate_status", "Check the status of a delegated sub-agent by its delegate_id."),
    ]
    existing_names = {r["name"] for r in rows}
    for tool_name, tool_desc in _DELEGATE_TOOLS:
        if tool_name in existing_names:
            continue
        trigger_status: dict[str, Any] = {}
        for trigger in TRIGGER_TYPES:
            tool_in_trigger = tool_name in set(trigger_explicit_tools.get(trigger, []))
            is_blocked = tool_name in set(trigger_blocked_tools.get(trigger, []))
            trigger_status[trigger] = {
                "enabled": tool_in_trigger,
                "explicitly_enabled": tool_in_trigger,
                "explicitly_blocked": is_blocked,
                "allowed_by_policy": tool_in_trigger and not is_blocked,
                "reason": "" if tool_in_trigger and not is_blocked else "Not enabled for this trigger",
            }
            if tool_in_trigger:
                trigger_effective_tools[trigger].append(tool_name)
        rows.append({
            "name": tool_name,
            "description": tool_desc,
            "permission_level": "L1_WRITE",
            "trigger_status": trigger_status,
        })

    return {
        "triggers": list(TRIGGER_TYPES),
        "enabled_tools": trigger_effective_tools,
        "explicit_enabled_tools": trigger_explicit_tools,
        "explicit_blocked_tools": trigger_blocked_tools,
        "tools": rows,
    }


def get_all_tools(
    base_dir: Path,
    runtime: RuntimeConfig,
    trigger_type: str = "chat",
    config_base_dir: Path | None = None,
):
    all_tools = _build_declared_tools(
        base_dir,
        runtime,
        config_base_dir=config_base_dir,
    )
    policy = ToolPolicyEngine()
    explicit_enabled_tools = get_explicit_enabled_tools(runtime, trigger_type)
    explicit_blocked_tools = get_explicit_blocked_tools(runtime, trigger_type)
    enabled: list[MiniTool] = []
    for tool in all_tools:
        decision = policy.is_allowed(
            tool_name=tool.name,
            permission_level=tool.permission_level,
            trigger_type=trigger_type,
            explicit_enabled_tools=explicit_enabled_tools,
            explicit_blocked_tools=explicit_blocked_tools,
        )
        if decision.allowed:
            enabled.append(tool)
    return enabled


def get_tool_runner(
    base_dir: Path,
    audit_store: AuditStore | None = None,
    repeat_identical_failure_limit: int = 2,
) -> ToolRunner:
    return ToolRunner(
        policy_engine=ToolPolicyEngine(),
        audit_file=base_dir / "storage" / "tool_audit.jsonl",
        audit_store=audit_store,
        repeat_identical_failure_limit=repeat_identical_failure_limit,
    )


__all__ = [
    "build_tool_catalog",
    "ensure_skills_snapshot",
    "get_all_declared_tools",
    "get_all_tools",
    "get_explicit_blocked_tools",
    "get_tool_runner",
    "scan_skills",
    "get_explicit_enabled_tools",
]
