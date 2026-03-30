"""Tests for Python REPL hardening."""
import tempfile
from pathlib import Path

import pytest
from tools.python_repl_tool import PythonReplTool
from tools.base import ToolContext


def _ctx():
    return ToolContext(
        workspace_root=Path(tempfile.gettempdir()),
        trigger_type="chat",
        run_id="r1",
        session_id="test",
    )


def test_class_chain_blocked():
    tool = PythonReplTool()
    result = tool.run({"code": "().__class__.__bases__[0].__subclasses__()"}, _ctx())
    assert not result.ok
    assert result.error is not None


def test_import_blocked():
    tool = PythonReplTool()
    result = tool.run({"code": "x = __import__('os')"}, _ctx())
    assert not result.ok


def test_getattr_blocked():
    tool = PythonReplTool()
    result = tool.run({"code": "getattr(int, '__bases__')"}, _ctx())
    assert not result.ok


def test_open_blocked():
    tool = PythonReplTool()
    result = tool.run({"code": "open('/etc/passwd')"}, _ctx())
    assert not result.ok


def test_eval_blocked():
    tool = PythonReplTool()
    result = tool.run({"code": "eval('1+1')"}, _ctx())
    assert not result.ok


def test_exec_blocked():
    tool = PythonReplTool()
    result = tool.run({"code": "exec('print(1)')"}, _ctx())
    assert not result.ok


def test_simple_math_allowed():
    tool = PythonReplTool()
    result = tool.run({"code": "print(2 + 2)"}, _ctx())
    assert result.ok
    assert "4" in result.data.get("output", "")


def test_list_comprehension_allowed():
    tool = PythonReplTool()
    result = tool.run({"code": "print([x**2 for x in range(5)])"}, _ctx())
    assert result.ok
    assert "[0, 1, 4, 9, 16]" in result.data.get("output", "")
