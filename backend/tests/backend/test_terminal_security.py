from __future__ import annotations

from pathlib import Path

from tools.base import ToolContext
from tools.terminal_tool import TerminalTool


def test_terminal_tool_scrubs_secret_environment(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("OPENAI_API_KEY", "super-secret")
    monkeypatch.setenv("SAFE_FLAG", "visible")

    tool = TerminalTool(
        root_dir=tmp_path,
        timeout_seconds=5,
        output_char_limit=5000,
        sandbox_mode="unsafe_none",
        require_sandbox=False,
        allowed_command_prefixes=("python3",),
    )
    context = ToolContext(workspace_root=tmp_path, trigger_type="chat")
    result = tool.run(
        {
            "command": (
                "python3 -c \"import os; "
                "print((os.getenv('OPENAI_API_KEY') or '') + '|' + "
                "(os.getenv('SAFE_FLAG') or ''))\""
            )
        },
        context,
    )

    assert result.ok is True
    combined = str(result.data.get("combined", ""))
    assert "super-secret" not in combined
    assert "|visible" in combined


def test_terminal_blocks_non_allowlisted_command(tmp_path: Path):
    tool = TerminalTool(
        root_dir=tmp_path,
        sandbox_mode="unsafe_none",
        require_sandbox=False,
        allowed_command_prefixes=("echo",),
    )
    context = ToolContext(workspace_root=tmp_path, trigger_type="chat")
    result = tool.run({"command": "ls"}, context)

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "E_POLICY_DENIED"


def test_terminal_fails_closed_when_sandbox_unavailable(monkeypatch, tmp_path: Path):
    import tools.terminal_tool as terminal_module
    from tools.sandbox import SandboxUnavailableError

    def _raise_unavailable(**kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        raise SandboxUnavailableError("sandbox backend unavailable")

    monkeypatch.setattr(terminal_module, "resolve_sandbox", _raise_unavailable)

    tool = TerminalTool(
        root_dir=tmp_path,
        sandbox_mode="darwin_sandbox",
        require_sandbox=True,
        allowed_command_prefixes=("echo",),
    )
    context = ToolContext(workspace_root=tmp_path, trigger_type="chat")
    result = tool.run({"command": "echo hi"}, context)

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "E_SANDBOX_UNAVAILABLE"


def test_terminal_fails_when_sandbox_enforcement_errors(monkeypatch, tmp_path: Path):
    import tools.terminal_tool as terminal_module

    class _FakeSandbox:
        backend_id = "darwin_sandbox_exec"
        mode = "hybrid_auto"

        @staticmethod
        def wrap_command(argv: list[str]) -> list[str]:
            _ = argv
            return [
                "python3",
                "-c",
                (
                    "import sys; "
                    "sys.stderr.write('sandbox-exec: sandbox_apply: Operation not permitted\\n'); "
                    "raise SystemExit(71)"
                ),
            ]

    monkeypatch.setattr(terminal_module, "resolve_sandbox", lambda **kwargs: _FakeSandbox())

    tool = TerminalTool(
        root_dir=tmp_path,
        sandbox_mode="hybrid_auto",
        require_sandbox=True,
        allowed_command_prefixes=("echo",),
    )
    context = ToolContext(workspace_root=tmp_path, trigger_type="chat")
    result = tool.run({"command": "echo hello"}, context)

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "E_SANDBOX_REQUIRED"
