"""Tests for approval store."""
import tempfile
from pathlib import Path
from storage.approval_store import ApprovalStore, ApprovalStatus


def test_create_and_get_request():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = ApprovalStore(Path(tmpdir))
        req = store.create_request(
            agent_id="default",
            session_id="sess-1",
            run_id="run-1",
            tool_name="terminal",
            tool_args={"command": "ls"},
            trigger_type="chat",
        )
        assert req.status == ApprovalStatus.PENDING

        fetched = store.get_request("default", req.request_id)
        assert fetched is not None
        assert fetched.tool_name == "terminal"
        assert fetched.status == ApprovalStatus.PENDING


def test_resolve_request():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = ApprovalStore(Path(tmpdir))
        req = store.create_request(
            agent_id="default",
            session_id="sess-1",
            run_id="run-1",
            tool_name="terminal",
            tool_args={"command": "ls"},
            trigger_type="chat",
        )
        store.resolve_request("default", req.request_id, ApprovalStatus.APPROVED)

        fetched = store.get_request("default", req.request_id)
        assert fetched is not None
        assert fetched.status == ApprovalStatus.APPROVED


def test_list_pending():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = ApprovalStore(Path(tmpdir))
        store.create_request(
            agent_id="default", session_id="s1", run_id="r1",
            tool_name="terminal", tool_args={}, trigger_type="chat",
        )
        pending = store.list_pending("default")
        assert len(pending) == 1

        store.resolve_request("default", pending[0].request_id, ApprovalStatus.DENIED)
        pending = store.list_pending("default")
        assert len(pending) == 0
