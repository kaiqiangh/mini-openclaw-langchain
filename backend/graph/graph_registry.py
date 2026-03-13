from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from graph.runtime_types import GraphRuntime, RuntimeCheckpointer, RuntimeRequest


class NullRuntimeCheckpointer:
    async def for_request(self, request: RuntimeRequest) -> None:
        _ = request
        return None

    async def delete_thread(self, *, agent_id: str, thread_id: str) -> None:
        _ = agent_id, thread_id


@dataclass(frozen=True)
class _RegisteredRuntime:
    factory: Callable[[], GraphRuntime]
    runtime: GraphRuntime | None = None


class GraphRuntimeRegistry:
    def __init__(self, checkpointer: RuntimeCheckpointer | None = None) -> None:
        self.checkpointer = checkpointer or NullRuntimeCheckpointer()
        self._entries: dict[str, _RegisteredRuntime] = {}

    def register(self, name: str, factory: Callable[[], GraphRuntime]) -> None:
        self._entries[name] = _RegisteredRuntime(factory=factory)

    def resolve(self, name: str) -> GraphRuntime:
        entry = self._entries.get(name)
        if entry is None:
            raise KeyError(f"Unknown graph runtime: {name}")
        if entry.runtime is None:
            runtime = entry.factory()
            self._entries[name] = _RegisteredRuntime(
                factory=entry.factory,
                runtime=runtime,
            )
            return runtime
        return entry.runtime
