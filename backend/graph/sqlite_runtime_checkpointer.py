from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable

import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from graph.checkpoint_serde import build_checkpoint_serializer
from graph.runtime_types import RuntimeCheckpointer, RuntimeRequest

if TYPE_CHECKING:
    from graph.agent import AgentRuntime


@dataclass
class _SaverEntry:
    saver: AsyncSqliteSaver
    db_path: Path


class SQLiteRuntimeCheckpointer(RuntimeCheckpointer):
    def __init__(
        self,
        *,
        runtime_getter: Callable[[str], AgentRuntime],
        filename: str = "langgraph_checkpoints.sqlite",
    ) -> None:
        self._runtime_getter = runtime_getter
        self._filename = filename
        self._entries: dict[tuple[str, int], _SaverEntry] = {}
        self._lock = asyncio.Lock()

    def checkpoint_path(self, agent_id: str) -> Path:
        runtime = self._runtime_getter(agent_id)
        path = runtime.root_dir / "storage" / self._filename
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    async def _get_saver(self, agent_id: str) -> AsyncSqliteSaver:
        loop = asyncio.get_running_loop()
        key = (agent_id, id(loop))
        cached = self._entries.get(key)
        if cached is not None:
            return cached.saver

        async with self._lock:
            cached = self._entries.get(key)
            if cached is not None:
                return cached.saver

            db_path = self.checkpoint_path(agent_id)
            conn = await aiosqlite.connect(str(db_path))
            saver = AsyncSqliteSaver(conn, serde=build_checkpoint_serializer())
            await saver.setup()
            self._entries[key] = _SaverEntry(saver=saver, db_path=db_path)
            return saver

    async def for_request(self, request: RuntimeRequest) -> AsyncSqliteSaver:
        return await self._get_saver(request.agent_id)

    async def delete_thread(self, *, agent_id: str, thread_id: str) -> None:
        saver = await self._get_saver(agent_id)
        await saver.adelete_thread(thread_id)
