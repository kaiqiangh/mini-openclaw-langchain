from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from langchain_core.tools import StructuredTool
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field, model_validator

from .base import MiniTool, ToolContext
from .runner import ToolRunner


class TerminalArgs(BaseModel):
    command: str = Field(
        description="Command to execute under terminal sandbox and policy rules"
    )
    timeout: int | None = Field(
        default=None, ge=1, le=300, description="Optional timeout in seconds"
    )


class PythonReplArgs(BaseModel):
    code: str = Field(description="Python code snippet to execute")


class FetchUrlArgs(BaseModel):
    url: str = Field(description="HTTP or HTTPS URL to fetch")
    extractMode: str | None = Field(
        default=None, description="One of markdown, text, html"
    )
    maxChars: int | None = Field(
        default=None, ge=256, le=100000, description="Optional max output chars"
    )


class ReadFilesArgs(BaseModel):
    path: str | None = Field(
        default=None, description="Optional workspace-relative single file path"
    )
    paths: list[str] | None = Field(
        default=None, description="Optional workspace-relative file paths"
    )
    start_line: int | None = Field(
        default=None, description="Optional 1-based start line"
    )
    end_line: int | None = Field(default=None, description="Optional 1-based end line")
    max_chars: int | None = Field(default=None, description="Optional max char limit")

    @model_validator(mode="after")
    def _validate_path_shape(self) -> "ReadFilesArgs":
        has_single = isinstance(self.path, str) and bool(self.path.strip())
        has_many = bool(self.paths)
        if not has_single and not has_many:
            raise ValueError("Provide either path or paths")
        return self


class ReadPdfArgs(BaseModel):
    path: str = Field(description="Workspace-relative .pdf file path")
    pages: list[int] | None = Field(
        default=None, description="Optional 1-based page numbers"
    )
    max_chars: int | None = Field(default=None, description="Optional max char limit")


class SearchKnowledgeArgs(BaseModel):
    query: str = Field(description="Search query")
    top_k: int = Field(default=3, ge=1, le=10, description="Top results count")


class WebSearchArgs(BaseModel):
    query: str = Field(description="Search query")
    limit: int | None = Field(
        default=None, ge=1, le=10, description="Optional max results"
    )
    count: int | None = Field(default=None, ge=1, le=10, description="Alias for limit")
    recency_days: int | None = Field(
        default=None, ge=1, le=3650, description="Optional recency filter in days"
    )
    allowed_domains: list[str] | None = Field(
        default=None, description="Optional allowed domain list"
    )
    blocked_domains: list[str] | None = Field(
        default=None, description="Optional blocked domain list"
    )


class SessionsListArgs(BaseModel):
    agent_id: str | None = Field(default=None, description="Optional agent id")
    scope: str | None = Field(
        default=None, description="Optional one of active, archived, all"
    )
    limit: int | None = Field(default=None, ge=1, le=1000, description="Max results")


class SessionHistoryArgs(BaseModel):
    session_id: str = Field(description="Session id to inspect")
    agent_id: str | None = Field(default=None, description="Optional agent id")
    archived: bool | None = Field(
        default=None, description="Read from archived sessions if true"
    )
    include_live: bool | None = Field(
        default=None, description="Include live streaming assistant response if present"
    )
    max_messages: int | None = Field(
        default=None, ge=1, le=5000, description="Max messages to return"
    )


class AgentsListArgs(BaseModel):
    include_stats: bool | None = Field(
        default=None, description="Reserved for future output tuning"
    )


class SchedulerAgentArgs(BaseModel):
    agent_id: str | None = Field(default=None, description="Optional agent id")


class SchedulerRunsArgs(BaseModel):
    agent_id: str | None = Field(default=None, description="Optional agent id")
    limit: int | None = Field(default=None, ge=1, le=5000, description="Max rows")


class ApplyPatchArgs(BaseModel):
    input: str = Field(description="Unified diff patch content")


def _result_to_json(result: Any) -> str:
    return json.dumps(asdict(result), ensure_ascii=False)


_TOOL_SCHEMAS: tuple[tuple[str, type[BaseModel]], ...] = (
    ("terminal", TerminalArgs),
    ("python_repl", PythonReplArgs),
    ("fetch_url", FetchUrlArgs),
    ("read_files", ReadFilesArgs),
    ("read_pdf", ReadPdfArgs),
    ("search_knowledge_base", SearchKnowledgeArgs),
    ("web_search", WebSearchArgs),
    ("sessions_list", SessionsListArgs),
    ("session_history", SessionHistoryArgs),
    ("agents_list", AgentsListArgs),
    ("scheduler_cron_jobs", SchedulerAgentArgs),
    ("scheduler_cron_runs", SchedulerRunsArgs),
    ("scheduler_heartbeat_status", SchedulerAgentArgs),
    ("scheduler_heartbeat_runs", SchedulerRunsArgs),
    ("apply_patch", ApplyPatchArgs),
)


def _register_tool(
    *,
    name: str,
    args_schema: type[BaseModel],
    by_name: dict[str, MiniTool],
    structured: list[StructuredTool],
    runner: ToolRunner,
    context: ToolContext,
) -> None:
    tool = by_name.get(name)
    if tool is None:
        return

    def invoke(config: RunnableConfig | None = None, **kwargs: Any) -> str:
        args = {key: value for key, value in kwargs.items() if value is not None}
        metadata = config.get("metadata", {}) if isinstance(config, dict) else {}
        tool_call_id = metadata.get("tool_call_id") if isinstance(metadata, dict) else None
        result = runner.run_tool(
            tool, args=args, context=context, tool_call_id=str(tool_call_id or "") or None
        )
        return _result_to_json(result)

    structured.append(
        StructuredTool.from_function(
            name=name,
            description=tool.description,
            func=invoke,
            args_schema=args_schema,
        )
    )


def build_langchain_tools(
    *,
    tools: list[MiniTool],
    runner: ToolRunner,
    context: ToolContext,
    delegate_tools: list[StructuredTool] | None = None,
) -> list[StructuredTool]:
    by_name = {tool.name: tool for tool in tools}
    structured: list[StructuredTool] = []

    for name, args_schema in _TOOL_SCHEMAS:
        _register_tool(
            name=name,
            args_schema=args_schema,
            by_name=by_name,
            structured=structured,
            runner=runner,
            context=context,
        )

    if delegate_tools:
        structured.extend(delegate_tools)
    return structured
