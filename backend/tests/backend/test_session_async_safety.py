"""Tests for async SessionManager concurrent access."""
import asyncio
import json
import tempfile
from pathlib import Path

import pytest


@pytest.mark.asyncio
async def test_concurrent_session_writes_do_not_corrupt():
    """Concurrent async session saves must not produce corrupt JSON."""
    from graph.session_manager import SessionManager

    with tempfile.TemporaryDirectory() as tmpdir:
        manager = SessionManager(Path(tmpdir))
        session_id = "concurrent-test"

        await manager.create_session(session_id)

        async def write_session(n: int):
            for _ in range(20):
                await manager.save_session(session_id, {"counter": n, "title": f"Session {n}"})

        await asyncio.gather(
            write_session(1),
            write_session(2),
            write_session(3),
        )

        session_path = Path(tmpdir) / "sessions" / f"{session_id}.json"
        data = json.loads(session_path.read_text())
        assert isinstance(data, dict)
        assert "counter" in data


@pytest.mark.asyncio
async def test_concurrent_create_and_list():
    """Concurrent session creation and listing must not conflict."""
    from graph.session_manager import SessionManager

    with tempfile.TemporaryDirectory() as tmpdir:
        manager = SessionManager(Path(tmpdir))

        async def create_sessions():
            for i in range(10):
                await manager.create_session(f"session-{i}", title=f"Session {i}")

        async def list_sessions():
            for _ in range(10):
                sessions = await manager.list_sessions()
                assert isinstance(sessions, list)

        await asyncio.gather(create_sessions(), list_sessions())


@pytest.mark.asyncio
async def test_session_manager_uses_asyncio_lock():
    """SessionManager must use asyncio.Lock, not threading.RLock."""
    from graph.session_manager import SessionManager
    import asyncio as aio

    with tempfile.TemporaryDirectory() as tmpdir:
        manager = SessionManager(Path(tmpdir))
        assert isinstance(manager._lock, aio.Lock)


@pytest.mark.asyncio
async def test_internal_sessions_are_hidden_from_counts_and_lists():
    """Internal child sessions must stay out of ordinary operator surfaces."""
    from graph.session_manager import SessionManager, count_session_files

    with tempfile.TemporaryDirectory() as tmpdir:
        manager = SessionManager(Path(tmpdir))
        await manager.create_session("public-1", title="Public Session")
        await manager.create_session(
            "child-1",
            title="Internal Child",
            hidden=True,
            internal=True,
            metadata={"session_kind": "delegate_child"},
        )

        visible = await manager.list_sessions()
        all_sessions = await manager.list_sessions(include_hidden=True)

        assert [row["session_id"] for row in visible] == ["public-1"]
        assert {row["session_id"] for row in all_sessions} == {"public-1", "child-1"}
        assert count_session_files(manager.sessions_dir) == 1
        assert count_session_files(manager.sessions_dir, include_hidden=True) == 2
