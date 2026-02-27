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


class PythonReplArgs(BaseModel):
    code: str = Field(description="Python code snippet to execute")


class FetchUrlArgs(BaseModel):
    url: str = Field(description="HTTP or HTTPS URL to fetch")


class ReadFileArgs(BaseModel):
    path: str = Field(description="Workspace-relative file path")
    start_line: int | None = Field(default=None, description="Optional 1-based start line")
    end_line: int | None = Field(default=None, description="Optional 1-based end line")
    max_chars: int | None = Field(default=None, description="Optional max char limit")


class SearchKnowledgeArgs(BaseModel):
    query: str = Field(description="Search query")
    top_k: int = Field(default=3, ge=1, le=10, description="Top results count")


def _result_to_json(result: Any) -> str:
    return json.dumps(asdict(result), ensure_ascii=False)


def build_langchain_tools(
    *,
    tools: list[MiniTool],
    runner: ToolRunner,
    context: ToolContext,
) -> list[StructuredTool]:
    by_name = {tool.name: tool for tool in tools}
    structured: list[StructuredTool] = []

    if "terminal" in by_name:
        tool = by_name["terminal"]

        def run_terminal(command: str) -> str:
            result = runner.run_tool(
                tool,
                args={"command": command},
                context=context,
            )
            return _result_to_json(result)

        structured.append(
            StructuredTool.from_function(
                name="terminal",
                description=tool.description,
                func=run_terminal,
                args_schema=TerminalArgs,
            )
        )

    if "python_repl" in by_name:
        tool = by_name["python_repl"]

        def run_python_repl(code: str) -> str:
            result = runner.run_tool(
                tool,
                args={"code": code},
                context=context,
            )
            return _result_to_json(result)

        structured.append(
            StructuredTool.from_function(
                name="python_repl",
                description=tool.description,
                func=run_python_repl,
                args_schema=PythonReplArgs,
            )
        )

    if "fetch_url" in by_name:
        tool = by_name["fetch_url"]

        def run_fetch_url(url: str) -> str:
            result = runner.run_tool(
                tool,
                args={"url": url},
                context=context,
            )
            return _result_to_json(result)

        structured.append(
            StructuredTool.from_function(
                name="fetch_url",
                description=tool.description,
                func=run_fetch_url,
                args_schema=FetchUrlArgs,
            )
        )

    if "read_file" in by_name:
        tool = by_name["read_file"]

        def run_read_file(
            path: str,
            start_line: int | None = None,
            end_line: int | None = None,
            max_chars: int | None = None,
        ) -> str:
            args: dict[str, Any] = {
                "path": path,
            }
            if start_line is not None:
                args["start_line"] = start_line
            if end_line is not None:
                args["end_line"] = end_line
            if max_chars is not None:
                args["max_chars"] = max_chars

            result = runner.run_tool(tool, args=args, context=context)
            return _result_to_json(result)

        structured.append(
            StructuredTool.from_function(
                name="read_file",
                description=tool.description,
                func=run_read_file,
                args_schema=ReadFileArgs,
            )
        )

    if "search_knowledge_base" in by_name:
        tool = by_name["search_knowledge_base"]

        def run_search_knowledge_base(query: str, top_k: int = 3) -> str:
            result = runner.run_tool(
                tool,
                args={"query": query, "top_k": top_k},
                context=context,
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

    return structured
