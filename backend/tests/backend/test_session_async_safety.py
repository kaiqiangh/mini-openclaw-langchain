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
