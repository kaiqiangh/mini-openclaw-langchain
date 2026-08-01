from __future__ import annotations

from pathlib import Path

import pytest

from graph.sqlite_runtime_checkpointer import _SaverEntry, SQLiteRuntimeCheckpointer


class _FakeConnection:
    def __init__(self) -> None:
        self.close_calls = 0

    async def close(self) -> None:
        self.close_calls += 1


class _FakeSaver:
    def __init__(self, conn: _FakeConnection) -> None:
        self.conn = conn


@pytest.mark.asyncio
async def test_close_closes_and_clears_cached_savers():
    checkpointer = SQLiteRuntimeCheckpointer(runtime_getter=lambda _: None)  # type: ignore[arg-type]
    connection = _FakeConnection()
    checkpointer._entries[("default", 1)] = _SaverEntry(
        saver=_FakeSaver(connection), db_path=Path("checkpoints.sqlite")  # type: ignore[arg-type]
    )

    await checkpointer.close()
    await checkpointer.close()

    assert connection.close_calls == 1
    assert checkpointer._entries == {}
