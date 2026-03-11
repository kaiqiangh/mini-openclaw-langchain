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


@dataclass
class _SearchTool:
    name: str
    description: str = "Returns success"
    permission_level: PermissionLevel = PermissionLevel.L2_NETWORK

    def run(self, args, context):  # type: ignore[no-untyped-def]
        _ = args, context
        return ToolResult.success(
            tool_name=self.name,
            data={"ok": True},
            duration_ms=1,
        )


def test_tool_runner_blocks_repeated_identical_failures(tmp_path: Path):
    runner = ToolRunner(
        policy_engine=ToolPolicyEngine(), audit_file=tmp_path / "audit.jsonl"
    )
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

    assert (
        first.ok is False and first.error is not None and first.error.code == "E_EXEC"
    )
    assert (
        second.ok is False
        and second.error is not None
        and second.error.code == "E_EXEC"
    )
    assert (
        third.ok is False
        and third.error is not None
        and third.error.code == "E_POLICY_DENIED"
    )
    assert "retry blocked" in third.error.message.lower()


def test_tool_runner_does_not_block_different_arguments(tmp_path: Path):
    runner = ToolRunner(
        policy_engine=ToolPolicyEngine(), audit_file=tmp_path / "audit.jsonl"
    )
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


def test_tool_runner_respects_configured_repeat_limit(tmp_path: Path):
    runner = ToolRunner(
        policy_engine=ToolPolicyEngine(),
        audit_file=tmp_path / "audit.jsonl",
        repeat_identical_failure_limit=1,
    )
    context = ToolContext(
        workspace_root=tmp_path,
        trigger_type="chat",
        run_id="run-3",
        session_id="session-3",
    )
    tool = _FailingTool()

    first = runner.run_tool(tool, args={"path": "x"}, context=context)
    second = runner.run_tool(tool, args={"path": "x"}, context=context)

    assert (
        first.ok is False and first.error is not None and first.error.code == "E_EXEC"
    )
    assert (
        second.ok is False
        and second.error is not None
        and second.error.code == "E_POLICY_DENIED"
    )


def test_tool_runner_blocks_repeated_identical_web_searches(tmp_path: Path):
    runner = ToolRunner(
        policy_engine=ToolPolicyEngine(), audit_file=tmp_path / "audit.jsonl"
    )
    context = ToolContext(
        workspace_root=tmp_path,
        trigger_type="chat",
        run_id="run-search-1",
        session_id="session-search-1",
    )
    tool = _SearchTool(name="web_search")

    first = runner.run_tool(
        tool, args={"query": "BSC meme breakout rank"}, context=context
    )
    second = runner.run_tool(
        tool, args={"query": "BSC meme breakout rank"}, context=context
    )

    assert first.ok is True
    assert second.ok is False
    assert second.error is not None
    assert second.error.code == "E_POLICY_DENIED"
    assert "web search" in second.error.message.lower()


def test_tool_runner_blocks_repeated_near_duplicate_web_searches(tmp_path: Path):
    runner = ToolRunner(
        policy_engine=ToolPolicyEngine(), audit_file=tmp_path / "audit.jsonl"
    )
    context = ToolContext(
        workspace_root=tmp_path,
        trigger_type="chat",
        run_id="run-search-2",
        session_id="session-search-2",
    )
    tool = _SearchTool(name="web_search")

    first = runner.run_tool(
        tool, args={"query": "BSC meme breakout rank"}, context=context
    )
    second = runner.run_tool(
        tool, args={"query": "BSC meme breakout rank alpha"}, context=context
    )
    third = runner.run_tool(
        tool, args={"query": "BSC meme breakout rank watch"}, context=context
    )

    assert first.ok is True
    assert second.ok is True
    assert third.ok is False
    assert third.error is not None
    assert third.error.code == "E_POLICY_DENIED"
    assert "near-duplicate" in third.error.message.lower()


def test_tool_runner_blocks_repeated_fetch_url_calls(tmp_path: Path):
    runner = ToolRunner(
        policy_engine=ToolPolicyEngine(), audit_file=tmp_path / "audit.jsonl"
    )
    context = ToolContext(
        workspace_root=tmp_path,
        trigger_type="chat",
        run_id="run-search-3",
        session_id="session-search-3",
    )
    tool = _SearchTool(name="fetch_url")

    first = runner.run_tool(
        tool, args={"url": "https://example.com/path?x=1"}, context=context
    )
    second = runner.run_tool(
        tool, args={"url": "https://example.com/path?x=2"}, context=context
    )

    assert first.ok is True
    assert second.ok is False
    assert second.error is not None
    assert second.error.code == "E_POLICY_DENIED"
    assert "same page" in second.error.message.lower()
