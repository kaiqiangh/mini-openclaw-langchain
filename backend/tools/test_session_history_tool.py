import asyncio
from pathlib import Path
from types import SimpleNamespace

from graph.session_manager import SessionManager
from tools.base import ToolContext
from tools.session_history_tool import SessionHistoryTool


class _Repository:
    async def load_snapshot(
        self,
        *,
        agent_id: str,
        session_id: str,
        archived: bool = False,
        include_live: bool = True,
    ):
        _ = agent_id, session_id, archived, include_live
        return SimpleNamespace(
            session_id="sub_hidden",
            agent_id="alpha",
            archived=False,
            messages=[{"role": "user", "content": "hidden delegate task"}],
            compressed_context="",
            live_response=None,
        )


class _Manager:
    def __init__(self, session_manager: SessionManager) -> None:
        self._session_manager = session_manager
        self._repo = _Repository()

    def get_runtime(self, agent_id: str = "default"):
        _ = agent_id
        return SimpleNamespace(session_manager=self._session_manager)

    def get_session_repository(self, agent_id: str = "default"):
        _ = agent_id
        return self._repo


def test_session_history_rejects_hidden_internal_sessions(tmp_path: Path):
    runtime_root = tmp_path / "workspaces" / "alpha"
    runtime_root.mkdir(parents=True, exist_ok=True)
    session_manager = SessionManager(runtime_root)
    asyncio.run(
        session_manager.create_session(
            "sub_hidden",
            title="Hidden child",
            hidden=True,
            internal=True,
            metadata={"session_kind": "delegate_child"},
        )
    )

    tool = SessionHistoryTool(runtime_root=runtime_root)
    tool._manager = _Manager(session_manager)

    result = tool.run(
        {"session_id": "sub_hidden"},
        ToolContext(
            workspace_root=runtime_root,
            trigger_type="chat",
            agent_id="alpha",
            session_id="parent",
        ),
    )

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "E_NOT_FOUND"
