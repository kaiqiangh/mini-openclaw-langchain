from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Protocol

import pytest

from config import RuntimeConfig, ToolOutputLimits, ToolTimeouts
from tools import get_all_tools, get_tool_runner
from tools.apply_patch_tool import ApplyPatchTool
from tools.base import MiniTool, ToolContext
from tools.contracts import ToolResult
from tools.fetch_url_tool import FetchUrlTool
from tools.langchain_tools import build_langchain_tools
from tools.web_search_tool import WebSearchTool


def _seed_workspace(root: Path) -> None:
    (root / "memory").mkdir(parents=True, exist_ok=True)
    (root / "knowledge").mkdir(parents=True, exist_ok=True)
    (root / "storage").mkdir(parents=True, exist_ok=True)
    (root / "memory" / "MEMORY.md").write_text("memory alpha line\n", encoding="utf-8")
    (root / "knowledge" / "note.md").write_text(
        "knowledge alpha beta\n", encoding="utf-8"
    )


class _InvokableTool(Protocol):
    name: str

    def invoke(self, input: dict[str, Any]) -> str: ...


def _build_tool_map(root: Path) -> tuple[dict[str, _InvokableTool], list[MiniTool]]:
    runtime = RuntimeConfig(
        tool_timeouts=ToolTimeouts(
            terminal_seconds=5, python_repl_seconds=2, fetch_url_seconds=5
        ),
        tool_output_limits=ToolOutputLimits(
            terminal_chars=5000, fetch_url_chars=5000, read_file_chars=10000
        ),
    )
    mini_tools = get_all_tools(root, runtime, trigger_type="chat", config_base_dir=root)
    runner = get_tool_runner(root)
    context = ToolContext(
        workspace_root=root,
        trigger_type="chat",
        run_id="run-test",
        session_id="sess-test",
    )
    langchain_tools = build_langchain_tools(
        tools=mini_tools, runner=runner, context=context
    )
    return {tool.name: tool for tool in langchain_tools}, mini_tools


def _parse_result(payload: str) -> dict[str, Any]:
    return json.loads(payload)


def test_langchain_wrapper_binding_regression(tmp_path, monkeypatch):
    _seed_workspace(tmp_path)
    tool_map, mini_tools = _build_tool_map(tmp_path)

    for tool in mini_tools:
        name = getattr(tool, "name")

        def fake_run(args, context, _name=name):  # type: ignore[no-untyped-def]
            _ = args, context
            return ToolResult.success(tool_name=_name, data={"ok": True}, duration_ms=1)

        monkeypatch.setattr(tool, "run", fake_run)

    invocations = {
        "terminal": {"command": "echo test"},
        "exec": {"command": "echo test"},
        "python_repl": {"code": "print(1)"},
        "fetch_url": {"url": "https://example.com"},
        "web_fetch": {"url": "https://example.com"},
        "read_file": {"path": "memory/MEMORY.md"},
        "read": {"path": "memory/MEMORY.md"},
        "read_files": {"paths": ["memory/MEMORY.md"]},
        "search_knowledge_base": {"query": "alpha"},
        "web_search": {"query": "alpha"},
        "apply_patch": {"input": "--- x\n+++ x\n@@ -0,0 +1 @@\n+x\n"},
    }

    for name, args in invocations.items():
        result = _parse_result(tool_map[name].invoke(args))  # type: ignore[call-arg]
        assert result["meta"]["tool_name"] == name


def test_langchain_integration_calls_correct_tools(tmp_path):
    _seed_workspace(tmp_path)
    tool_map, _ = _build_tool_map(tmp_path)

    read_result = _parse_result(tool_map["read_file"].invoke({"path": "memory/MEMORY.md"}))  # type: ignore[call-arg]
    terminal_result = _parse_result(tool_map["terminal"].invoke({"command": "echo hi"}))  # type: ignore[call-arg]
    search_result = _parse_result(tool_map["search_knowledge_base"].invoke({"query": "alpha"}))  # type: ignore[call-arg]

    assert read_result["ok"] is True
    assert read_result["meta"]["tool_name"] == "read_file"
    assert terminal_result["ok"] is True
    assert terminal_result["meta"]["tool_name"] == "terminal"
    assert search_result["meta"]["tool_name"] == "search_knowledge_base"


def test_alias_parity_exec_read_and_web_fetch(tmp_path, monkeypatch):
    _seed_workspace(tmp_path)
    tool_map, _ = _build_tool_map(tmp_path)

    class _FakeResponse:
        status = 200
        headers = {"Content-Type": "text/html; charset=utf-8"}

        def __init__(self) -> None:
            self._sent = False

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            _ = exc_type, exc, tb
            return None

        def read(self, n=0) -> bytes:  # noqa: ARG002
            if self._sent:
                return b""
            self._sent = True
            return b"<html><body><h1>Title</h1><p>Hello</p></body></html>"

        def geturl(self) -> str:
            return "https://example.com"

    import tools.fetch_url_tool as fetch_module

    class _FakeOpener:
        def open(self, request, timeout=0):  # noqa: D401
            _ = request, timeout
            return _FakeResponse()

    monkeypatch.setattr(fetch_module, "build_opener", lambda *args, **kwargs: _FakeOpener())  # type: ignore[no-untyped-call]

    command = "printf 'a|b' | tr '|' ':'"
    terminal_result = _parse_result(tool_map["terminal"].invoke({"command": command}))  # type: ignore[call-arg]
    exec_result = _parse_result(tool_map["exec"].invoke({"command": command}))  # type: ignore[call-arg]
    assert terminal_result["ok"] is True
    assert exec_result["ok"] is True
    assert "a:b" in terminal_result["data"]["combined"]
    assert terminal_result["data"]["combined"] == exec_result["data"]["combined"]

    read_file_result = _parse_result(tool_map["read_file"].invoke({"path": "memory/MEMORY.md"}))  # type: ignore[call-arg]
    read_result = _parse_result(tool_map["read"].invoke({"path": "memory/MEMORY.md"}))  # type: ignore[call-arg]
    assert read_file_result["data"]["content"] == read_result["data"]["content"]

    fetch_result = _parse_result(tool_map["fetch_url"].invoke({"url": "https://example.com"}))  # type: ignore[call-arg]
    web_fetch_result = _parse_result(tool_map["web_fetch"].invoke({"url": "https://example.com"}))  # type: ignore[call-arg]
    assert fetch_result["data"]["content"] == web_fetch_result["data"]["content"]
    assert fetch_result["data"]["extract_mode"] == "markdown"
    assert web_fetch_result["data"]["extract_mode"] == "markdown"


def test_read_files_partial_failure(tmp_path):
    _seed_workspace(tmp_path)
    tool_map, _ = _build_tool_map(tmp_path)

    result = _parse_result(
        tool_map["read_files"].invoke({"paths": ["memory/MEMORY.md", "../etc/passwd"]})  # type: ignore[call-arg]
    )
    assert result["ok"] is True
    assert result["data"]["partial"] is True
    rows = result["data"]["results"]
    assert rows[0]["ok"] is True
    assert rows[1]["ok"] is False
    assert rows[1]["error"]["code"] == "E_INVALID_PATH"


def test_web_fetch_extract_mode_matrix(tmp_path, monkeypatch):
    _seed_workspace(tmp_path)
    context = ToolContext(workspace_root=tmp_path, trigger_type="chat")
    tool = FetchUrlTool(timeout_seconds=2, output_char_limit=200)

    class _FakeResponse:
        status = 200
        headers = {"Content-Type": "text/html; charset=utf-8"}

        def __init__(self) -> None:
            self._sent = False

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            _ = exc_type, exc, tb
            return None

        def read(self, n=0) -> bytes:  # noqa: ARG002
            if self._sent:
                return b""
            self._sent = True
            body = (
                "<html><body><h1>Title</h1><p>"
                + ("Hello world " * 80)
                + "</p></body></html>"
            )
            return body.encode("utf-8")

        def geturl(self) -> str:
            return "https://example.com"

    import tools.fetch_url_tool as fetch_module

    class _FakeOpener:
        def open(self, request, timeout=0):  # noqa: D401
            _ = request, timeout
            return _FakeResponse()

    monkeypatch.setattr(fetch_module, "build_opener", lambda *args, **kwargs: _FakeOpener())  # type: ignore[no-untyped-call]

    markdown = tool.run(
        {"url": "https://example.com", "extractMode": "markdown"}, context
    )
    html = tool.run({"url": "https://example.com", "extractMode": "html"}, context)
    text = tool.run({"url": "https://example.com", "extractMode": "text"}, context)
    truncated = tool.run(
        {"url": "https://example.com", "extractMode": "html", "maxChars": 256}, context
    )

    assert markdown.ok is True
    assert html.ok is True
    assert text.ok is True
    assert "<html" in str(html.data["content"]).lower()
    assert "<html" not in str(text.data["content"]).lower()
    assert truncated.ok is True
    assert truncated.data["truncated"] is True


def test_web_search_filters_and_limit(tmp_path, monkeypatch):
    _seed_workspace(tmp_path)
    context = ToolContext(workspace_root=tmp_path, trigger_type="chat")
    tool = WebSearchTool(timeout_seconds=1)

    class _FakeDDGS:
        def __init__(self, timeout):
            _ = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            _ = exc_type, exc, tb
            return None

        def text(self, query, max_results):  # noqa: D401
            _ = query, max_results
            return [
                {
                    "title": "Docs",
                    "href": "https://docs.openclaw.ai/tools",
                    "body": "doc",
                },
                {
                    "title": "Example",
                    "href": "https://example.com/page",
                    "body": "example",
                },
                {
                    "title": "Blocked",
                    "href": "https://blocked.com/page",
                    "body": "blocked",
                },
            ]

    import tools.web_search_tool as search_module

    monkeypatch.setattr(search_module, "DDGS", _FakeDDGS)

    result = tool.run(
        {
            "query": "openclaw tools",
            "limit": 2,
            "allowed_domains": ["openclaw.ai", "example.com"],
            "blocked_domains": ["blocked.com"],
        },
        context,
    )

    assert result.ok is True
    rows = result.data["results"]
    assert len(rows) == 2
    assert rows[0]["url"].startswith("https://docs.openclaw.ai")
    assert rows[1]["url"].startswith("https://example.com")


def test_web_search_dedupe_and_recency(tmp_path, monkeypatch):
    _seed_workspace(tmp_path)
    context = ToolContext(workspace_root=tmp_path, trigger_type="chat")
    tool = WebSearchTool(timeout_seconds=1)

    calls: dict[str, object] = {}

    class _FakeDDGS:
        def __init__(self, timeout):
            _ = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            _ = exc_type, exc, tb
            return None

        def text(self, query, max_results, timelimit=None):  # noqa: D401
            calls["query"] = query
            calls["max_results"] = max_results
            calls["timelimit"] = timelimit
            return [
                {"title": "A", "href": "https://example.com/docs?a=1", "body": "one"},
                {"title": "B", "href": "https://example.com/docs?a=2", "body": "two"},
                {"title": "C", "href": "https://example.com/guide", "body": "three"},
            ]

    import tools.web_search_tool as search_module

    monkeypatch.setattr(search_module, "DDGS", _FakeDDGS)

    result = tool.run({"query": "alpha", "limit": 5, "recency_days": 1}, context)
    assert result.ok is True
    assert calls["timelimit"] == "d"
    rows = result.data["results"]
    assert len(rows) == 2
    assert rows[0]["canonical_url"] == "https://example.com/docs"


def test_apply_patch_happy_path_and_path_guard(tmp_path):
    if shutil.which("patch") is None:
        pytest.skip("system patch command is unavailable")

    context = ToolContext(workspace_root=tmp_path, trigger_type="chat")
    tool = ApplyPatchTool(root_dir=tmp_path, timeout_seconds=5)

    target = tmp_path / "note.txt"
    target.write_text("hello\n", encoding="utf-8")

    ok_patch = "\n".join(
        [
            "--- note.txt",
            "+++ note.txt",
            "@@ -1 +1 @@",
            "-hello",
            "+world",
            "",
        ]
    )
    ok_result = tool.run({"input": ok_patch}, context)
    assert ok_result.ok is True
    assert ok_result.data["applied"] is True
    assert ok_result.data["changed_files"] == ["note.txt"]
    assert target.read_text(encoding="utf-8") == "world\n"

    bad_patch = "\n".join(
        [
            "--- ../evil.txt",
            "+++ ../evil.txt",
            "@@ -0,0 +1 @@",
            "+owned",
            "",
        ]
    )
    bad_result = tool.run({"input": bad_patch}, context)
    assert bad_result.ok is False
    assert bad_result.error is not None
    assert bad_result.error.code == "E_INVALID_PATH"
