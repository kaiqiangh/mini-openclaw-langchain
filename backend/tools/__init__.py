from __future__ import annotations

from pathlib import Path

from config import RuntimeConfig
from storage.run_store import AuditStore

from .apply_patch_tool import ApplyPatchTool
from .base import MiniTool
from .fetch_url_tool import FetchUrlTool
from .policy import ToolPolicyEngine
from .python_repl_tool import PythonReplTool
from .read_file_tool import ReadFileTool
from .read_files_tool import ReadFilesTool
from .runner import ToolRunner
from .search_knowledge_tool import SearchKnowledgeTool
from .skills_scanner import scan_skills
from .terminal_tool import TerminalTool
from .web_search_tool import WebSearchTool


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
        TerminalTool(
            root_dir=base_dir,
            timeout_seconds=runtime.tool_timeouts.terminal_seconds,
            output_char_limit=runtime.tool_output_limits.terminal_chars,
            name="exec",
            description="Execute shell commands in workspace sandbox",
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
        FetchUrlTool(
            timeout_seconds=runtime.tool_timeouts.fetch_url_seconds,
            output_char_limit=runtime.tool_output_limits.fetch_url_chars,
            allowed_schemes=tuple(runtime.tool_network.allow_http_schemes),
            block_private_networks=runtime.tool_network.block_private_networks,
            max_redirects=runtime.tool_network.max_redirects,
            max_content_bytes=runtime.tool_network.max_content_bytes,
            name="web_fetch",
            description="Fetch remote URL and extract content",
        ),
        ReadFileTool(
            root_dir=base_dir,
            max_chars_default=runtime.tool_output_limits.read_file_chars,
        ),
        ReadFileTool(
            root_dir=base_dir,
            max_chars_default=runtime.tool_output_limits.read_file_chars,
            name="read",
            description="Read workspace file content safely",
        ),
        ReadFilesTool(
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
        WebSearchTool(timeout_seconds=runtime.tool_timeouts.fetch_url_seconds),
        ApplyPatchTool(
            root_dir=base_dir, timeout_seconds=runtime.tool_timeouts.terminal_seconds
        ),
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
    "get_all_tools",
    "get_tool_runner",
    "scan_skills",
    "get_explicit_enabled_tools",
]
