from __future__ import annotations

import asyncio
from typing import Any

from config import RuntimeConfig
from graph.agent_loop_types import RetrievalEnvelope


class RetrievalOrchestrator:
    _MAX_CONTEXT_CHARS = 20_000

    @classmethod
    def _format_context(cls, results: list[dict[str, Any]]) -> str | None:
        lines: list[str] = []
        total_chars = 0
        for item in results:
            line = f"- ({item['score']}) {item['text']}"
            remaining = cls._MAX_CONTEXT_CHARS - total_chars
            if remaining <= 0:
                break
            lines.append(line[:remaining])
            total_chars += min(len(line), remaining)
        return "[Memory Retrieval Results]\n" + "\n".join(lines) if lines else None

    @staticmethod
    def build_envelope(
        *,
        runtime: RuntimeConfig,
        memory_indexer: Any,
        message: str,
    ) -> RetrievalEnvelope:
        if not runtime.rag_mode:
            return RetrievalEnvelope(rag_mode=False)

        results = memory_indexer.retrieve(
            message,
            settings=runtime.retrieval.memory,
        )
        rag_context = RetrievalOrchestrator._format_context(results)
        return RetrievalEnvelope(
            rag_mode=True,
            results=results,
            rag_context=rag_context,
        )

    @staticmethod
    async def abuild_envelope(
        *,
        runtime: RuntimeConfig,
        memory_indexer: Any,
        message: str,
    ) -> RetrievalEnvelope:
        if not runtime.rag_mode:
            return RetrievalEnvelope(rag_mode=False)

        aretrieve = getattr(memory_indexer, "aretrieve", None)
        if callable(aretrieve):
            results = await aretrieve(message, settings=runtime.retrieval.memory)
        else:
            results = await asyncio.to_thread(
                memory_indexer.retrieve,
                message,
                settings=runtime.retrieval.memory,
            )
        rag_context = RetrievalOrchestrator._format_context(results)
        return RetrievalEnvelope(
            rag_mode=True,
            results=results,
            rag_context=rag_context,
        )
