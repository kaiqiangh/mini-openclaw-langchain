from __future__ import annotations

from pathlib import Path

from config import RuntimeConfig
from storage.run_store import AuditStore

from .base import MiniTool
from .fetch_url_tool import FetchUrlTool
from .policy import ToolPolicyEngine
from .python_repl_tool import PythonReplTool
from .read_file_tool import ReadFileTool
from .runner import ToolRunner
from .search_knowledge_tool import SearchKnowledgeTool
from .skills_scanner import scan_skills
from .terminal_tool import TerminalTool


def get_explicit_enabled_tools(runtime: RuntimeConfig, trigger_type: str) -> list[str]:
    if trigger_type == "heartbeat":
        return list(runtime.autonomous_tools.heartbeat_enabled_tools)
    if trigger_type == "cron":
        return list(runtime.autonomous_tools.cron_enabled_tools)
    return []


def get_all_tools(
    base_dir: Path,
    runtime: RuntimeConfig,
    trigger_type: str = "chat",
    config_base_dir: Path | None = None,
):
    all_tools: list[MiniTool] = [
        TerminalTool(
            root_dir=base_dir,
            timeout_seconds=runtime.tool_timeouts.terminal_seconds,
            output_char_limit=runtime.tool_output_limits.terminal_chars,
        ),
        PythonReplTool(
            output_char_limit=runtime.tool_output_limits.terminal_chars,
        ),
        FetchUrlTool(
            timeout_seconds=runtime.tool_timeouts.fetch_url_seconds,
            output_char_limit=runtime.tool_output_limits.fetch_url_chars,
        ),
        ReadFileTool(
            root_dir=base_dir,
            max_chars_default=runtime.tool_output_limits.read_file_chars,
        ),
        SearchKnowledgeTool(root_dir=base_dir, config_base_dir=config_base_dir),
    ]

    policy = ToolPolicyEngine()
    explicit_enabled_tools = get_explicit_enabled_tools(runtime, trigger_type)
    enabled: list[MiniTool] = []
    for tool in all_tools:
        decision = policy.is_allowed(
            tool_name=tool.name,
            permission_level=tool.permission_level,
            trigger_type=trigger_type,
            explicit_enabled_tools=explicit_enabled_tools,
        )
        if decision.allowed:
            enabled.append(tool)
    return enabled


def get_tool_runner(base_dir: Path, audit_store: AuditStore | None = None) -> ToolRunner:
    return ToolRunner(
        policy_engine=ToolPolicyEngine(),
        audit_file=base_dir / "storage" / "tool_audit.jsonl",
        audit_store=audit_store,
    )


__all__ = ["get_all_tools", "get_tool_runner", "scan_skills", "get_explicit_enabled_tools"]
