from __future__ import annotations

import pytest

from tools.base import ToolContext
from tools.terminal_tool import TerminalTool


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf /",
        "echo hi; uname -a",
        "echo $(whoami)",
        "bash -lc 'echo hi'",
        "curl https://example.com",
    ],
)
def test_terminal_malicious_command_corpus_is_denied(tmp_path, command: str):
    tool = TerminalTool(
        root_dir=tmp_path,
        timeout_seconds=5,
        output_char_limit=5000,
        sandbox_mode="unsafe_none",
        require_sandbox=False,
        allowed_command_prefixes=("echo",),
        allow_shell_syntax=False,
    )
    context = ToolContext(workspace_root=tmp_path, trigger_type="chat")
    result = tool.run({"command": command}, context)

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "E_POLICY_DENIED"

