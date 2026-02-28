from __future__ import annotations

from tools.contracts import ToolResult
from tools.python_repl_tool import PythonReplTool
from tools.terminal_tool import TerminalTool


def test_toolresult_success_and_failure_shapes():
    ok = ToolResult.success(tool_name="x", data={"a": 1}, duration_ms=12)
    assert ok.ok is True
    assert ok.error is None
    assert ok.meta.tool_name == "x"

    err = ToolResult.failure(
        tool_name="x", code="E_TIMEOUT", message="boom", duration_ms=9, retryable=True
    )
    assert err.ok is False
    assert err.error is not None
    assert err.error.code == "E_TIMEOUT"
    assert err.error.retryable is True


def test_terminal_timeout_contract(tmp_path):
    tool = TerminalTool(root_dir=tmp_path, timeout_seconds=1, output_char_limit=200)
    result = tool.run({"command": 'python3 -c "import time; time.sleep(2)"'}, context=None)  # type: ignore[arg-type]

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "E_TIMEOUT"


def test_python_repl_timeout_contract():
    tool = PythonReplTool(timeout_seconds=1, output_char_limit=200)
    result = tool.run({"code": "while True:\n    pass"}, context=None)  # type: ignore[arg-type]

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "E_TIMEOUT"
