from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from graph.session_manager import (
    InvalidSessionIdError,
    SessionManager,
    encode_session_path_component,
    validate_session_id,
)
from tools.sessions_list_tool import SessionsListTool


@pytest.mark.parametrize(
    "session_id",
    ["", ".", "..", "../escape", "nested/session", "nested\\session", "bad\nvalue", "x" * 129],
)
def test_validate_session_id_rejects_path_and_control_input(session_id: str):
    with pytest.raises(InvalidSessionIdError):
        validate_session_id(session_id)


@pytest.mark.parametrize(
    "session_id",
    [
        "550e8400-e29b-41d4-a716-446655440000",
        "sub_0123abcd",
        "__heartbeat__",
        "__cron__:cron-1",
        "replay:run-1:0123abcd",
    ],
)
def test_validate_session_id_preserves_existing_logical_forms(session_id: str):
    assert validate_session_id(session_id) == session_id


@pytest.mark.asyncio
async def test_session_manager_rejects_invalid_ids_without_writing_outside_root(
    tmp_path: Path,
):
    manager = SessionManager(tmp_path)
    outside = tmp_path / "escape.json"

    with pytest.raises(InvalidSessionIdError):
        await manager.create_session("../escape")

    assert not outside.exists()


@pytest.mark.asyncio
async def test_colon_bearing_ids_are_encoded_on_disk_and_round_trip(tmp_path: Path):
    manager = SessionManager(tmp_path)
    session_id = "__cron__:cron-1"

    await manager.create_session(session_id)

    encoded_path = manager.sessions_dir / f"{encode_session_path_component(session_id)}.json"
    assert encoded_path.exists()
    assert await manager.load_existing_session(session_id)
    assert any(item["session_id"] == session_id for item in await manager.list_sessions())


def test_session_manager_rejects_symlinked_session_files(tmp_path: Path):
    manager = SessionManager(tmp_path)
    outside = tmp_path / "outside.json"
    outside.write_text("{}\n", encoding="utf-8")
    (manager.sessions_dir / "session-1.json").symlink_to(outside)

    with pytest.raises(InvalidSessionIdError):
        asyncio.run(manager.load_existing_session("session-1"))


def test_session_archive_path_uses_safe_encoded_component(tmp_path: Path):
    manager = SessionManager(tmp_path)

    archive_path = manager.session_archive_path("__cron__:cron-1", 123)
    assert archive_path.name == "__cron__%3Acron-1_123.json"

    with pytest.raises(InvalidSessionIdError):
        manager.session_archive_path("../escape", 123)


@pytest.mark.asyncio
async def test_existing_colon_bearing_legacy_files_still_round_trip(tmp_path: Path):
    manager = SessionManager(tmp_path)
    session_id = "__cron__:legacy"
    legacy_path = manager.sessions_dir / f"{session_id}.json"
    legacy_path.write_text('{"title":"legacy"}\n', encoding="utf-8")

    assert (await manager.load_existing_session(session_id))["title"] == "legacy"
    assert any(item["session_id"] == session_id for item in await manager.list_sessions())


def test_sessions_list_tool_returns_logical_ids_for_encoded_paths(tmp_path: Path):
    manager = SessionManager(tmp_path)
    session_id = "__cron__:cron-1"
    asyncio.run(manager.create_session(session_id))

    listed = SessionsListTool._list_sessions_sync(manager)

    assert listed[0]["session_id"] == session_id
