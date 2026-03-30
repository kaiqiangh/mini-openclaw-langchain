"""Tests for _active_runs cleanup."""
import asyncio
import pytest


@pytest.mark.asyncio
async def test_active_runs_cleaned_after_close():
    """_active_runs must not leak after stream task completes."""
    from api.chat import _active_runs, _active_runs_lock, _StreamRunState, _close_run

    key = "test-agent:test-session-cleanup"
    async with _active_runs_lock:
        state = _StreamRunState(
            key=key,
            agent_id="test-agent",
            session_id="test-session-cleanup",
            message="test",
        )
        _active_runs[key] = state

    # Verify it's there
    async with _active_runs_lock:
        assert key in _active_runs

    # Close it
    await _close_run(state)

    # Verify it's removed
    async with _active_runs_lock:
        assert key not in _active_runs, "Run must be removed after close"
