from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from .base import MiniTool, ToolContext
from .runner import ToolRunner


class TerminalArgs(BaseModel):
    command: str = Field(description="Shell command to execute in workspace sandbox")
    timeout: int | None = Field(default=None, ge=1, le=300, description="Optional timeout in seconds")


class PythonReplArgs(BaseModel):
    code: str = Field(description="Python code snippet to execute")


class FetchUrlArgs(BaseModel):
    url: str = Field(description="HTTP or HTTPS URL to fetch")
    extractMode: str | None = Field(default=None, description="One of markdown, text, html")
    maxChars: int | None = Field(default=None, ge=256, le=100000, description="Optional max output chars")


class ReadFileArgs(BaseModel):
    path: str = Field(description="Workspace-relative file path")
    start_line: int | None = Field(default=None, description="Optional 1-based start line")
    end_line: int | None = Field(default=None, description="Optional 1-based end line")
    max_chars: int | None = Field(default=None, description="Optional max char limit")


class ReadFilesArgs(BaseModel):
    paths: list[str] = Field(description="Workspace-relative file paths")
    start_line: int | None = Field(default=None, description="Optional 1-based start line")
    end_line: int | None = Field(default=None, description="Optional 1-based end line")
    max_chars: int | None = Field(default=None, description="Optional max char limit")


class SearchKnowledgeArgs(BaseModel):
    query: str = Field(description="Search query")
    top_k: int = Field(default=3, ge=1, le=10, description="Top results count")


class WebSearchArgs(BaseModel):
    query: str = Field(description="Search query")
    limit: int | None = Field(default=None, ge=1, le=10, description="Optional max results")
    count: int | None = Field(default=None, ge=1, le=10, description="Alias for limit")
    allowed_domains: list[str] | None = Field(default=None, description="Optional allowed domain list")
    blocked_domains: list[str] | None = Field(default=None, description="Optional blocked domain list")


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
    tool_name: str,
) -> None:
    if tool_name not in by_name:
        return
    tool = by_name[tool_name]

    def run_terminal(command: str, timeout: int | None = None, _tool: MiniTool = tool) -> str:
        args: dict[str, Any] = {"command": command}
        if timeout is not None:
            args["timeout"] = timeout
        result = runner.run_tool(_tool, args=args, context=context)
        return _result_to_json(result)

    structured.append(
        StructuredTool.from_function(
            name=tool_name,
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
    tool_name: str,
) -> None:
    if tool_name not in by_name:
        return
    tool = by_name[tool_name]

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
            name=tool_name,
            description=tool.description,
            func=run_fetch_url,
            args_schema=FetchUrlArgs,
        )
    )


def _register_read_file_tool(
    *,
    by_name: dict[str, MiniTool],
    structured: list[StructuredTool],
    runner: ToolRunner,
    context: ToolContext,
    tool_name: str,
) -> None:
    if tool_name not in by_name:
        return
    tool = by_name[tool_name]

    def run_read_file(
        path: str,
        start_line: int | None = None,
        end_line: int | None = None,
        max_chars: int | None = None,
        _tool: MiniTool = tool,
    ) -> str:
        args: dict[str, Any] = {"path": path}
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
            name=tool_name,
            description=tool.description,
            func=run_read_file,
            args_schema=ReadFileArgs,
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
        paths: list[str],
        start_line: int | None = None,
        end_line: int | None = None,
        max_chars: int | None = None,
        _tool: MiniTool = tool,
    ) -> str:
        args: dict[str, Any] = {"paths": paths}
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

    def run_search_knowledge_base(query: str, top_k: int = 3, _tool: MiniTool = tool) -> str:
        result = runner.run_tool(_tool, args={"query": query, "top_k": top_k}, context=context)
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
        allowed_domains: list[str] | None = None,
        blocked_domains: list[str] | None = None,
        _tool: MiniTool = tool,
    ) -> str:
        args: dict[str, Any] = {"query": query}
        if limit is not None:
            args["limit"] = limit
        if count is not None:
            args["count"] = count
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

    _register_terminal_tool(by_name=by_name, structured=structured, runner=runner, context=context, tool_name="terminal")
    _register_terminal_tool(by_name=by_name, structured=structured, runner=runner, context=context, tool_name="exec")
    _register_python_tool(by_name=by_name, structured=structured, runner=runner, context=context)
    _register_fetch_tool(by_name=by_name, structured=structured, runner=runner, context=context, tool_name="fetch_url")
    _register_fetch_tool(by_name=by_name, structured=structured, runner=runner, context=context, tool_name="web_fetch")
    _register_read_file_tool(by_name=by_name, structured=structured, runner=runner, context=context, tool_name="read_file")
    _register_read_file_tool(by_name=by_name, structured=structured, runner=runner, context=context, tool_name="read")
    _register_read_files_tool(by_name=by_name, structured=structured, runner=runner, context=context)
    _register_search_knowledge_tool(by_name=by_name, structured=structured, runner=runner, context=context)
    _register_web_search_tool(by_name=by_name, structured=structured, runner=runner, context=context)
    _register_apply_patch_tool(by_name=by_name, structured=structured, runner=runner, context=context)

    return structured
