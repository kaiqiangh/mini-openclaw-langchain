from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tools.base import ToolContext
from tools.contracts import ToolResult
from tools.policy import PermissionLevel, ToolPolicyEngine
from tools.runner import ToolRunner


@dataclass
class _FailingTool:
    name: str = "failing_tool"
    description: str = "Always fails"
    permission_level: PermissionLevel = PermissionLevel.L0_READ

    def run(self, args, context):  # type: ignore[no-untyped-def]
        _ = args, context
        return ToolResult.failure(
            tool_name=self.name,
            code="E_EXEC",
            message="simulated failure",
            duration_ms=1,
            retryable=False,
        )


def test_tool_runner_blocks_repeated_identical_failures(tmp_path: Path):
    runner = ToolRunner(policy_engine=ToolPolicyEngine(), audit_file=tmp_path / "audit.jsonl")
    context = ToolContext(
        workspace_root=tmp_path,
        trigger_type="chat",
        run_id="run-1",
        session_id="session-1",
    )
    tool = _FailingTool()

    first = runner.run_tool(tool, args={"path": "a"}, context=context)
    second = runner.run_tool(tool, args={"path": "a"}, context=context)
    third = runner.run_tool(tool, args={"path": "a"}, context=context)

    assert first.ok is False and first.error is not None and first.error.code == "E_EXEC"
    assert second.ok is False and second.error is not None and second.error.code == "E_EXEC"
    assert third.ok is False and third.error is not None and third.error.code == "E_POLICY_DENIED"
    assert "retry blocked" in third.error.message.lower()


def test_tool_runner_does_not_block_different_arguments(tmp_path: Path):
    runner = ToolRunner(policy_engine=ToolPolicyEngine(), audit_file=tmp_path / "audit.jsonl")
    context = ToolContext(
        workspace_root=tmp_path,
        trigger_type="chat",
        run_id="run-2",
        session_id="session-2",
    )
    tool = _FailingTool()

    _ = runner.run_tool(tool, args={"path": "a"}, context=context)
    _ = runner.run_tool(tool, args={"path": "a"}, context=context)
    different = runner.run_tool(tool, args={"path": "b"}, context=context)

    assert different.ok is False
    assert different.error is not None
    assert different.error.code == "E_EXEC"
