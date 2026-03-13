from __future__ import annotations
import json
import shutil
import time
from pathlib import Path
from typing import Any, Protocol

import pytest

from config import RuntimeConfig, ToolOutputLimits, ToolTimeouts
from graph.agent import AgentManager
from tools import get_all_tools, get_tool_runner
from tools.apply_patch_tool import ApplyPatchTool
from tools.base import MiniTool, ToolContext
from tools.contracts import ToolResult
from tools.fetch_url_tool import FetchUrlTool
from tools.langchain_tools import build_langchain_tools
from tools.web_search_tool import WebSearchTool


def _write_session(path: Path, title: str, messages: list[dict[str, Any]]) -> None:
    now = time.time()
    payload = {
        "title": title,
        "created_at": now,
        "updated_at": now,
        "compressed_context": "",
        "messages": messages,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _seed_workspace(root: Path) -> None:
    for rel in [
        "workspace",
        "memory",
        "knowledge",
        "storage",
        "sessions",
        "sessions/archived_sessions",
        "workspaces/elon/workspace",
        "workspaces/elon/sessions",
        "workspaces/elon/sessions/archived_sessions",
    ]:
        (root / rel).mkdir(parents=True, exist_ok=True)

    (root / "memory" / "MEMORY.md").write_text("memory alpha line\n", encoding="utf-8")
    (root / "knowledge" / "note.md").write_text("knowledge alpha beta\n", encoding="utf-8")
    (root / "workspace" / "HEARTBEAT.md").write_text("ping heartbeat", encoding="utf-8")
    (root / "config.json").write_text("{}\n", encoding="utf-8")

    _write_session(
        root / "sessions" / "sess-alpha.json",
        "Alpha Session",
        [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ],
    )
    _write_session(
        root / "workspaces" / "elon" / "sessions" / "sess-elon.json",
        "Elon Session",
        [{"role": "user", "content": "status?"}],
    )

    (root / "storage" / "cron_jobs.json").write_text(
        json.dumps(
            {
                "jobs": [
                    {
                        "id": "job-1",
                        "name": "sample",
                        "schedule_type": "every",
                        "schedule": "60",
                        "prompt": "ping",
                        "enabled": True,
                        "next_run_ts": time.time(),
                        "created_at": time.time(),
                        "updated_at": time.time(),
                    }
                ]
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "storage" / "cron_runs.jsonl").write_text(
        json.dumps({"job_id": "job-1", "status": "ok", "duration_ms": 23}) + "\n",
        encoding="utf-8",
    )
    (root / "storage" / "heartbeat_runs.jsonl").write_text(
        json.dumps({"status": "ok", "duration_ms": 12}) + "\n",
        encoding="utf-8",
    )

    (root / "sample.pdf").write_bytes(b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF")


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
    runtime.chat_enabled_tools = ["terminal"]
    runtime.tool_execution.terminal.sandbox_mode = "unsafe_none"
    runtime.tool_execution.terminal.require_sandbox = False
    runtime.tool_execution.terminal.allowed_command_prefixes = [
        "echo",
        "printf",
        "python3",
    ]
    mini_tools = get_all_tools(root, runtime, trigger_type="chat", config_base_dir=root)
    runner = get_tool_runner(root)
    context = ToolContext(
        workspace_root=root,
        trigger_type="chat",
        explicit_enabled_tools=tuple(runtime.chat_enabled_tools),
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
        "python_repl": {"code": "print(1)"},
        "fetch_url": {"url": "https://example.com"},
        "read_files": {"path": "memory/MEMORY.md"},
        "read_pdf": {"path": "sample.pdf"},
        "search_knowledge_base": {"query": "alpha"},
        "web_search": {"query": "alpha"},
        "sessions_list": {"scope": "all"},
        "session_history": {"session_id": "sess-alpha"},
        "agents_list": {},
        "scheduler_cron_jobs": {},
        "scheduler_cron_runs": {},
        "scheduler_heartbeat_status": {},
        "scheduler_heartbeat_runs": {},
        "apply_patch": {"input": "--- x\n+++ x\n@@ -0,0 +1 @@\n+x\n"},
    }

    for name, args in invocations.items():
        result = _parse_result(tool_map[name].invoke(args))  # type: ignore[call-arg]
        assert result["meta"]["tool_name"] == name


def test_removed_aliases_are_not_registered(tmp_path):
    _seed_workspace(tmp_path)
    tool_map, _ = _build_tool_map(tmp_path)
    assert "exec" not in tool_map
    assert "web_fetch" not in tool_map
    assert "read_file" not in tool_map
    assert "read" not in tool_map


def test_langchain_integration_calls_correct_tools(tmp_path):
    _seed_workspace(tmp_path)
    tool_map, _ = _build_tool_map(tmp_path)

    read_result = _parse_result(tool_map["read_files"].invoke({"path": "memory/MEMORY.md"}))  # type: ignore[call-arg]
    terminal_result = _parse_result(tool_map["terminal"].invoke({"command": "echo hi"}))  # type: ignore[call-arg]
    search_result = _parse_result(tool_map["search_knowledge_base"].invoke({"query": "alpha"}))  # type: ignore[call-arg]

    assert read_result["ok"] is True
    assert read_result["meta"]["tool_name"] == "read_files"
    assert terminal_result["ok"] is True
    assert terminal_result["meta"]["tool_name"] == "terminal"
    assert search_result["meta"]["tool_name"] == "search_knowledge_base"


def test_read_files_single_and_multi_path_modes(tmp_path):
    _seed_workspace(tmp_path)
    tool_map, _ = _build_tool_map(tmp_path)

    single = _parse_result(
        tool_map["read_files"].invoke({"path": "memory/MEMORY.md"})  # type: ignore[call-arg]
    )
    assert single["ok"] is True
    assert single["data"]["results"][0]["ok"] is True

    multi = _parse_result(
        tool_map["read_files"].invoke(  # type: ignore[call-arg]
            {"paths": ["memory/MEMORY.md", "../etc/passwd"]}
        )
    )
    assert multi["ok"] is True
    assert multi["data"]["partial"] is True
    rows = multi["data"]["results"]
    assert rows[0]["ok"] is True
    assert rows[1]["ok"] is False
    assert rows[1]["error"]["code"] == "E_INVALID_PATH"


def test_management_tools_return_workspace_state(tmp_path):
    _seed_workspace(tmp_path)
    manager = AgentManager()
    manager.initialize(tmp_path)
    default_root = manager.get_runtime("default").root_dir
    for name in ("cron_jobs.json", "cron_runs.jsonl", "heartbeat_runs.jsonl"):
        shutil.copy2(tmp_path / "storage" / name, default_root / "storage" / name)
    tool_map, _ = _build_tool_map(tmp_path)

    sessions = _parse_result(
        tool_map["sessions_list"].invoke({"scope": "all"})  # type: ignore[call-arg]
    )
    assert sessions["ok"] is True
    assert sessions["data"]["count"] >= 1

    history = _parse_result(
        tool_map["session_history"].invoke({"session_id": "sess-alpha"})  # type: ignore[call-arg]
    )
    assert history["ok"] is True
    assert history["data"]["message_count"] == 2
    assert [row["content"] for row in history["data"]["messages"]] == ["hello", "hi"]

    agents = _parse_result(tool_map["agents_list"].invoke({}))  # type: ignore[call-arg]
    assert agents["ok"] is True
    assert agents["data"]["count"] >= 1

    cron_jobs = _parse_result(
        tool_map["scheduler_cron_jobs"].invoke({})  # type: ignore[call-arg]
    )
    assert cron_jobs["ok"] is True
    assert cron_jobs["data"]["count"] >= 1

    cron_runs = _parse_result(
        tool_map["scheduler_cron_runs"].invoke({"limit": 10})  # type: ignore[call-arg]
    )
    assert cron_runs["ok"] is True

    heartbeat_status = _parse_result(
        tool_map["scheduler_heartbeat_status"].invoke({})  # type: ignore[call-arg]
    )
    assert heartbeat_status["ok"] is True
    assert "config" in heartbeat_status["data"]

    heartbeat_runs = _parse_result(
        tool_map["scheduler_heartbeat_runs"].invoke({"limit": 10})  # type: ignore[call-arg]
    )
    assert heartbeat_runs["ok"] is True


def test_fetch_url_extract_mode_matrix(tmp_path, monkeypatch):
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
