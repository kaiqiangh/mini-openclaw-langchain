from __future__ import annotations

from pathlib import Path

from tools.base import ToolContext
from tools.terminal_tool import TerminalTool


def test_terminal_tool_scrubs_secret_environment(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("OPENAI_API_KEY", "super-secret")
    monkeypatch.setenv("SAFE_FLAG", "visible")
    script_path = tmp_path / "show_env.py"
    script_path.write_text(
        (
            "import os\n"
            "print((os.getenv('OPENAI_API_KEY') or '') + '|' + "
            "(os.getenv('SAFE_FLAG') or ''))\n"
        ),
        encoding="utf-8",
    )

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
        {"command": f"python3 {script_path.name}"},
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


def test_terminal_builtin_denied_prefix_overrides_allowlist(tmp_path: Path):
    tool = TerminalTool(
        root_dir=tmp_path,
        sandbox_mode="unsafe_none",
        require_sandbox=False,
        allowed_command_prefixes=("rm",),
    )
    context = ToolContext(workspace_root=tmp_path, trigger_type="chat")
    result = tool.run({"command": "rm scratch.txt"}, context)

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "E_POLICY_DENIED"
    assert result.error.details["matched_policy_rule"] == "rm"


def test_terminal_allows_safe_command_in_denylist_mode(tmp_path: Path):
    tool = TerminalTool(
        root_dir=tmp_path,
        sandbox_mode="unsafe_none",
        command_policy_mode="denylist",
        require_sandbox=False,
    )
    context = ToolContext(workspace_root=tmp_path, trigger_type="chat")
    result = tool.run({"command": "date +%Y-%m-%d"}, context)

    assert result.ok is True
    assert result.data["effective_policy_mode"] == "denylist"


def test_terminal_auto_mode_uses_allowlist_without_sandbox(
    monkeypatch, tmp_path: Path
):
    class _UnsafeSandbox:
        backend_id = "unsafe_none"
        mode = "hybrid_auto"

        @staticmethod
        def wrap_command(argv: list[str]) -> list[str]:
            return argv

    monkeypatch.setattr(
        "tools.terminal_tool.resolve_sandbox",
        lambda **kwargs: _UnsafeSandbox(),
    )

    tool = TerminalTool(
        root_dir=tmp_path,
        sandbox_mode="hybrid_auto",
        command_policy_mode="auto",
        require_sandbox=False,
    )
    context = ToolContext(workspace_root=tmp_path, trigger_type="chat")
    result = tool.run({"command": "echo hi"}, context)

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "E_POLICY_DENIED"
    assert result.error.details["effective_policy_mode"] == "allowlist"


def test_terminal_auto_mode_uses_denylist_with_active_sandbox(
    monkeypatch, tmp_path: Path
):
    class _Sandboxed:
        backend_id = "linux_bwrap"
        mode = "hybrid_auto"

        @staticmethod
        def wrap_command(argv: list[str]) -> list[str]:
            return argv

    monkeypatch.setattr(
        "tools.terminal_tool.resolve_sandbox",
        lambda **kwargs: _Sandboxed(),
    )

    tool = TerminalTool(
        root_dir=tmp_path,
        sandbox_mode="hybrid_auto",
        command_policy_mode="auto",
        require_sandbox=True,
    )
    context = ToolContext(workspace_root=tmp_path, trigger_type="chat")
    result = tool.run({"command": "echo hi"}, context)

    assert result.ok is True
    assert result.data["effective_policy_mode"] == "denylist"


def test_terminal_custom_denied_prefix_blocks_safe_command(tmp_path: Path):
    tool = TerminalTool(
        root_dir=tmp_path,
        sandbox_mode="unsafe_none",
        command_policy_mode="denylist",
        require_sandbox=False,
        denied_command_prefixes=("date",),
    )
    context = ToolContext(workspace_root=tmp_path, trigger_type="chat")
    result = tool.run({"command": "date +%Y-%m-%d"}, context)

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "E_POLICY_DENIED"
    assert result.error.details["matched_policy_rule"] == "date"


def test_terminal_blocks_network_command_when_network_disabled(tmp_path: Path):
    tool = TerminalTool(
        root_dir=tmp_path,
        sandbox_mode="unsafe_none",
        command_policy_mode="denylist",
        require_sandbox=False,
        allow_network=False,
    )
    context = ToolContext(workspace_root=tmp_path, trigger_type="chat")
    result = tool.run({"command": "curl https://example.com"}, context)

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "E_POLICY_DENIED"
    assert result.error.details["matched_policy_rule"] == "curl"


def test_terminal_fails_closed_when_sandbox_unavailable(monkeypatch, tmp_path: Path):
    from tools.sandbox import SandboxUnavailableError

    def _raise_unavailable(**kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        raise SandboxUnavailableError("sandbox backend unavailable")

    monkeypatch.setattr("tools.terminal_tool.resolve_sandbox", _raise_unavailable)

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

    monkeypatch.setattr(
        "tools.terminal_tool.resolve_sandbox",
        lambda **kwargs: _FakeSandbox(),
    )

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
