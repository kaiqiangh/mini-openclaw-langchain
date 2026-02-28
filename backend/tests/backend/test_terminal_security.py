from __future__ import annotations

from pathlib import Path

from tools.base import ToolContext
from tools.terminal_tool import TerminalTool


def test_terminal_tool_scrubs_secret_environment(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("OPENAI_API_KEY", "super-secret")
    monkeypatch.setenv("SAFE_FLAG", "visible")

    tool = TerminalTool(root_dir=tmp_path, timeout_seconds=5, output_char_limit=5000)
    context = ToolContext(workspace_root=tmp_path, trigger_type="chat")
    result = tool.run(
        {"command": "printf '%s' \"${OPENAI_API_KEY:-}|${SAFE_FLAG:-}\""}, context
    )

    assert result.ok is True
    combined = str(result.data.get("combined", ""))
    assert "super-secret" not in combined
    assert "|visible" in combined
