from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from langchain_core.tools import StructuredTool
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


def _register_terminal_tool(
    *,
    by_name: dict[str, MiniTool],
    structured: list[StructuredTool],
    runner: ToolRunner,
    context: ToolContext,
) -> None:
    if "terminal" not in by_name:
        return
    tool = by_name["terminal"]

    def run_terminal(
        command: str, timeout: int | None = None, _tool: MiniTool = tool
    ) -> str:
        args: dict[str, Any] = {"command": command}
        if timeout is not None:
            args["timeout"] = timeout
        result = runner.run_tool(_tool, args=args, context=context)
        return _result_to_json(result)

    structured.append(
        StructuredTool.from_function(
            name="terminal",
            description=tool.description,
            func=run_terminal,
            args_schema=TerminalArgs,
        )
    )


def _register_python_tool(
    *,
    by_name: dict[str, MiniTool],
    structured: list[StructuredTool],
    runner: ToolRunner,
    context: ToolContext,
) -> None:
    if "python_repl" not in by_name:
        return
    tool = by_name["python_repl"]

    def run_python_repl(code: str, _tool: MiniTool = tool) -> str:
        result = runner.run_tool(_tool, args={"code": code}, context=context)
        return _result_to_json(result)

    structured.append(
        StructuredTool.from_function(
            name="python_repl",
            description=tool.description,
            func=run_python_repl,
            args_schema=PythonReplArgs,
        )
    )


def _register_fetch_tool(
    *,
    by_name: dict[str, MiniTool],
    structured: list[StructuredTool],
    runner: ToolRunner,
    context: ToolContext,
) -> None:
    if "fetch_url" not in by_name:
        return
    tool = by_name["fetch_url"]

    def run_fetch_url(
        url: str,
        extractMode: str | None = None,
        maxChars: int | None = None,
        _tool: MiniTool = tool,
    ) -> str:
        args: dict[str, Any] = {"url": url}
        if extractMode is not None:
            args["extractMode"] = extractMode
        if maxChars is not None:
            args["maxChars"] = maxChars
        result = runner.run_tool(_tool, args=args, context=context)
        return _result_to_json(result)

    structured.append(
        StructuredTool.from_function(
            name="fetch_url",
            description=tool.description,
            func=run_fetch_url,
            args_schema=FetchUrlArgs,
        )
    )


def _register_read_files_tool(
    *,
    by_name: dict[str, MiniTool],
    structured: list[StructuredTool],
    runner: ToolRunner,
    context: ToolContext,
) -> None:
    if "read_files" not in by_name:
        return
    tool = by_name["read_files"]

    def run_read_files(
        path: str | None = None,
        paths: list[str] | None = None,
        start_line: int | None = None,
        end_line: int | None = None,
        max_chars: int | None = None,
        _tool: MiniTool = tool,
    ) -> str:
        args: dict[str, Any] = {}
        if path is not None:
            args["path"] = path
        if paths is not None:
            args["paths"] = paths
        if start_line is not None:
            args["start_line"] = start_line
        if end_line is not None:
            args["end_line"] = end_line
        if max_chars is not None:
            args["max_chars"] = max_chars
        result = runner.run_tool(_tool, args=args, context=context)
        return _result_to_json(result)

    structured.append(
        StructuredTool.from_function(
            name="read_files",
            description=tool.description,
            func=run_read_files,
            args_schema=ReadFilesArgs,
        )
    )


def _register_read_pdf_tool(
    *,
    by_name: dict[str, MiniTool],
    structured: list[StructuredTool],
    runner: ToolRunner,
    context: ToolContext,
) -> None:
    if "read_pdf" not in by_name:
        return
    tool = by_name["read_pdf"]

    def run_read_pdf(
        path: str,
        pages: list[int] | None = None,
        max_chars: int | None = None,
        _tool: MiniTool = tool,
    ) -> str:
        args: dict[str, Any] = {"path": path}
        if pages is not None:
            args["pages"] = pages
        if max_chars is not None:
            args["max_chars"] = max_chars
        result = runner.run_tool(_tool, args=args, context=context)
        return _result_to_json(result)

    structured.append(
        StructuredTool.from_function(
            name="read_pdf",
            description=tool.description,
            func=run_read_pdf,
            args_schema=ReadPdfArgs,
        )
    )


def _register_search_knowledge_tool(
    *,
    by_name: dict[str, MiniTool],
    structured: list[StructuredTool],
    runner: ToolRunner,
    context: ToolContext,
) -> None:
    if "search_knowledge_base" not in by_name:
        return
    tool = by_name["search_knowledge_base"]

    def run_search_knowledge_base(
        query: str, top_k: int = 3, _tool: MiniTool = tool
    ) -> str:
        result = runner.run_tool(
            _tool, args={"query": query, "top_k": top_k}, context=context
        )
        return _result_to_json(result)

    structured.append(
        StructuredTool.from_function(
            name="search_knowledge_base",
            description=tool.description,
            func=run_search_knowledge_base,
            args_schema=SearchKnowledgeArgs,
        )
    )


def _register_web_search_tool(
    *,
    by_name: dict[str, MiniTool],
    structured: list[StructuredTool],
    runner: ToolRunner,
    context: ToolContext,
) -> None:
    if "web_search" not in by_name:
        return
    tool = by_name["web_search"]

    def run_web_search(
        query: str,
        limit: int | None = None,
        count: int | None = None,
        recency_days: int | None = None,
        allowed_domains: list[str] | None = None,
        blocked_domains: list[str] | None = None,
        _tool: MiniTool = tool,
    ) -> str:
        args: dict[str, Any] = {"query": query}
        if limit is not None:
            args["limit"] = limit
        if count is not None:
            args["count"] = count
        if recency_days is not None:
            args["recency_days"] = recency_days
        if allowed_domains is not None:
            args["allowed_domains"] = allowed_domains
        if blocked_domains is not None:
            args["blocked_domains"] = blocked_domains
        result = runner.run_tool(_tool, args=args, context=context)
        return _result_to_json(result)

    structured.append(
        StructuredTool.from_function(
            name="web_search",
            description=tool.description,
            func=run_web_search,
            args_schema=WebSearchArgs,
        )
    )


def _register_sessions_list_tool(
    *,
    by_name: dict[str, MiniTool],
    structured: list[StructuredTool],
    runner: ToolRunner,
    context: ToolContext,
) -> None:
    if "sessions_list" not in by_name:
        return
    tool = by_name["sessions_list"]

    def run_sessions_list(
        agent_id: str | None = None,
        scope: str | None = None,
        limit: int | None = None,
        _tool: MiniTool = tool,
    ) -> str:
        args: dict[str, Any] = {}
        if agent_id is not None:
            args["agent_id"] = agent_id
        if scope is not None:
            args["scope"] = scope
        if limit is not None:
            args["limit"] = limit
        result = runner.run_tool(_tool, args=args, context=context)
        return _result_to_json(result)

    structured.append(
        StructuredTool.from_function(
            name="sessions_list",
            description=tool.description,
            func=run_sessions_list,
            args_schema=SessionsListArgs,
        )
    )


def _register_session_history_tool(
    *,
    by_name: dict[str, MiniTool],
    structured: list[StructuredTool],
    runner: ToolRunner,
    context: ToolContext,
) -> None:
    if "session_history" not in by_name:
        return
    tool = by_name["session_history"]

    def run_session_history(
        session_id: str,
        agent_id: str | None = None,
        archived: bool | None = None,
        include_live: bool | None = None,
        max_messages: int | None = None,
        _tool: MiniTool = tool,
    ) -> str:
        args: dict[str, Any] = {"session_id": session_id}
        if agent_id is not None:
            args["agent_id"] = agent_id
        if archived is not None:
            args["archived"] = archived
        if include_live is not None:
            args["include_live"] = include_live
        if max_messages is not None:
            args["max_messages"] = max_messages
        result = runner.run_tool(_tool, args=args, context=context)
        return _result_to_json(result)

    structured.append(
        StructuredTool.from_function(
            name="session_history",
            description=tool.description,
            func=run_session_history,
            args_schema=SessionHistoryArgs,
        )
    )


def _register_agents_list_tool(
    *,
    by_name: dict[str, MiniTool],
    structured: list[StructuredTool],
    runner: ToolRunner,
    context: ToolContext,
) -> None:
    if "agents_list" not in by_name:
        return
    tool = by_name["agents_list"]

    def run_agents_list(
        include_stats: bool | None = None, _tool: MiniTool = tool
    ) -> str:
        args: dict[str, Any] = {}
        if include_stats is not None:
            args["include_stats"] = include_stats
        result = runner.run_tool(_tool, args=args, context=context)
        return _result_to_json(result)

    structured.append(
        StructuredTool.from_function(
            name="agents_list",
            description=tool.description,
            func=run_agents_list,
            args_schema=AgentsListArgs,
        )
    )


def _register_scheduler_cron_jobs_tool(
    *,
    by_name: dict[str, MiniTool],
    structured: list[StructuredTool],
    runner: ToolRunner,
    context: ToolContext,
) -> None:
    if "scheduler_cron_jobs" not in by_name:
        return
    tool = by_name["scheduler_cron_jobs"]

    def run_scheduler_cron_jobs(
        agent_id: str | None = None, _tool: MiniTool = tool
    ) -> str:
        args: dict[str, Any] = {}
        if agent_id is not None:
            args["agent_id"] = agent_id
        result = runner.run_tool(_tool, args=args, context=context)
        return _result_to_json(result)

    structured.append(
        StructuredTool.from_function(
            name="scheduler_cron_jobs",
            description=tool.description,
            func=run_scheduler_cron_jobs,
            args_schema=SchedulerAgentArgs,
        )
    )


def _register_scheduler_cron_runs_tool(
    *,
    by_name: dict[str, MiniTool],
    structured: list[StructuredTool],
    runner: ToolRunner,
    context: ToolContext,
) -> None:
    if "scheduler_cron_runs" not in by_name:
        return
    tool = by_name["scheduler_cron_runs"]

    def run_scheduler_cron_runs(
        agent_id: str | None = None,
        limit: int | None = None,
        _tool: MiniTool = tool,
    ) -> str:
        args: dict[str, Any] = {}
        if agent_id is not None:
            args["agent_id"] = agent_id
        if limit is not None:
            args["limit"] = limit
        result = runner.run_tool(_tool, args=args, context=context)
        return _result_to_json(result)

    structured.append(
        StructuredTool.from_function(
            name="scheduler_cron_runs",
            description=tool.description,
            func=run_scheduler_cron_runs,
            args_schema=SchedulerRunsArgs,
        )
    )


def _register_scheduler_heartbeat_status_tool(
    *,
    by_name: dict[str, MiniTool],
    structured: list[StructuredTool],
    runner: ToolRunner,
    context: ToolContext,
) -> None:
    if "scheduler_heartbeat_status" not in by_name:
        return
    tool = by_name["scheduler_heartbeat_status"]

    def run_scheduler_heartbeat_status(
        agent_id: str | None = None, _tool: MiniTool = tool
    ) -> str:
        args: dict[str, Any] = {}
        if agent_id is not None:
            args["agent_id"] = agent_id
        result = runner.run_tool(_tool, args=args, context=context)
        return _result_to_json(result)

    structured.append(
        StructuredTool.from_function(
            name="scheduler_heartbeat_status",
            description=tool.description,
            func=run_scheduler_heartbeat_status,
            args_schema=SchedulerAgentArgs,
        )
    )


def _register_scheduler_heartbeat_runs_tool(
    *,
    by_name: dict[str, MiniTool],
    structured: list[StructuredTool],
    runner: ToolRunner,
    context: ToolContext,
) -> None:
    if "scheduler_heartbeat_runs" not in by_name:
        return
    tool = by_name["scheduler_heartbeat_runs"]

    def run_scheduler_heartbeat_runs(
        agent_id: str | None = None,
        limit: int | None = None,
        _tool: MiniTool = tool,
    ) -> str:
        args: dict[str, Any] = {}
        if agent_id is not None:
            args["agent_id"] = agent_id
        if limit is not None:
            args["limit"] = limit
        result = runner.run_tool(_tool, args=args, context=context)
        return _result_to_json(result)

    structured.append(
        StructuredTool.from_function(
            name="scheduler_heartbeat_runs",
            description=tool.description,
            func=run_scheduler_heartbeat_runs,
            args_schema=SchedulerRunsArgs,
        )
    )


def _register_apply_patch_tool(
    *,
    by_name: dict[str, MiniTool],
    structured: list[StructuredTool],
    runner: ToolRunner,
    context: ToolContext,
) -> None:
    if "apply_patch" not in by_name:
        return
    tool = by_name["apply_patch"]

    def run_apply_patch(input: str, _tool: MiniTool = tool) -> str:
        result = runner.run_tool(_tool, args={"input": input}, context=context)
        return _result_to_json(result)

    structured.append(
        StructuredTool.from_function(
            name="apply_patch",
            description=tool.description,
            func=run_apply_patch,
            args_schema=ApplyPatchArgs,
        )
    )


def build_langchain_tools(
    *,
    tools: list[MiniTool],
    runner: ToolRunner,
    context: ToolContext,
) -> list[StructuredTool]:
    by_name = {tool.name: tool for tool in tools}
    structured: list[StructuredTool] = []

    _register_terminal_tool(
        by_name=by_name, structured=structured, runner=runner, context=context
    )
    _register_python_tool(
        by_name=by_name, structured=structured, runner=runner, context=context
    )
    _register_fetch_tool(
        by_name=by_name, structured=structured, runner=runner, context=context
    )
    _register_read_files_tool(
        by_name=by_name, structured=structured, runner=runner, context=context
    )
    _register_read_pdf_tool(
        by_name=by_name, structured=structured, runner=runner, context=context
    )
    _register_search_knowledge_tool(
        by_name=by_name, structured=structured, runner=runner, context=context
    )
    _register_web_search_tool(
        by_name=by_name, structured=structured, runner=runner, context=context
    )
    _register_sessions_list_tool(
        by_name=by_name, structured=structured, runner=runner, context=context
    )
    _register_session_history_tool(
        by_name=by_name, structured=structured, runner=runner, context=context
    )
    _register_agents_list_tool(
        by_name=by_name, structured=structured, runner=runner, context=context
    )
    _register_scheduler_cron_jobs_tool(
        by_name=by_name, structured=structured, runner=runner, context=context
    )
    _register_scheduler_cron_runs_tool(
        by_name=by_name, structured=structured, runner=runner, context=context
    )
    _register_scheduler_heartbeat_status_tool(
        by_name=by_name, structured=structured, runner=runner, context=context
    )
    _register_scheduler_heartbeat_runs_tool(
        by_name=by_name, structured=structured, runner=runner, context=context
    )
    _register_apply_patch_tool(
        by_name=by_name, structured=structured, runner=runner, context=context
    )

    return structured
