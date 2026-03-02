from __future__ import annotations

from pathlib import Path

import pytest

from control.coordinator import InMemoryCoordinator, SQLiteCoordinator


def _build_coordinator(kind: str, tmp_path: Path):
    if kind == "sqlite":
        return SQLiteCoordinator(tmp_path / "control.db")
    return InMemoryCoordinator()


@pytest.mark.parametrize("kind", ["in_memory", "sqlite"])
def test_stream_lock_exclusive(kind: str, tmp_path: Path):
    coordinator = _build_coordinator(kind, tmp_path)
    key = "agent:session"
    owner_a = "owner-a"
    owner_b = "owner-b"

    assert coordinator.acquire_stream_lock(key, owner_a, ttl_seconds=30) is True
    assert coordinator.acquire_stream_lock(key, owner_b, ttl_seconds=30) is False

    coordinator.release_stream_lock(key, owner_a)
    assert coordinator.acquire_stream_lock(key, owner_b, ttl_seconds=30) is True


@pytest.mark.parametrize("kind", ["in_memory", "sqlite"])
def test_rate_limit_window(kind: str, tmp_path: Path):
    coordinator = _build_coordinator(kind, tmp_path)
    key = "127.0.0.1:/api/v1/chat"

    first = coordinator.check_rate_limit(key, limit=1, window_seconds=60)
    second = coordinator.check_rate_limit(key, limit=1, window_seconds=60)

    assert first.allowed is True
    assert second.allowed is False
    assert second.retry_after_seconds >= 1

