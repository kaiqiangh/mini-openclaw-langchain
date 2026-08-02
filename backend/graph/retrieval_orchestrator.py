from __future__ import annotations

import asyncio
from typing import Any

from config import RuntimeConfig
from graph.agent_loop_types import RetrievalEnvelope


class RetrievalOrchestrator:
    _MAX_CONTEXT_CHARS = 20_000
    _MAX_RESULT_TEXT_CHARS = 4_000

    @classmethod
    def _bound_results(cls, results: Any) -> list[dict[str, Any]]:
        bounded: list[dict[str, Any]] = []
        for item in list(results or [])[:20]:
            if not isinstance(item, dict):
                continue
            row = dict(item)
            if "score" not in row:
                row["score"] = 0
            text = str(row.get("text", ""))
            if not text:
                continue
            if len(text) > cls._MAX_RESULT_TEXT_CHARS:
                row["text"] = text[: cls._MAX_RESULT_TEXT_CHARS] + "\n...[truncated]"
                row["truncated"] = True
            bounded.append(row)
        return bounded

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
    def _degradation(memory_indexer: Any) -> str | None:
        status_fn = getattr(memory_indexer, "status", None)
        if not callable(status_fn):
            return None
        status = status_fn()
        state = str(status.get("state", "")) if isinstance(status, dict) else ""
        if state == "building":
            return "index_building"
        if state == "failed":
            return "index_unavailable"
        return None

    @staticmethod
    def build_envelope(
        *,
        runtime: RuntimeConfig,
        memory_indexer: Any,
        message: str,
    ) -> RetrievalEnvelope:
        if not runtime.rag_mode:
            return RetrievalEnvelope(rag_mode=False)

        try:
            results = memory_indexer.retrieve(
                message,
                settings=runtime.retrieval.memory,
            )
        except Exception:
            return RetrievalEnvelope(rag_mode=True, degradation="index_unavailable")
        results = RetrievalOrchestrator._bound_results(results)
        rag_context = RetrievalOrchestrator._format_context(results)
        return RetrievalEnvelope(
            rag_mode=True,
            results=results,
            rag_context=rag_context,
            degradation=RetrievalOrchestrator._degradation(memory_indexer),
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
            try:
                results = await aretrieve(message, settings=runtime.retrieval.memory)
            except Exception:
                return RetrievalEnvelope(
                    rag_mode=True, degradation="index_unavailable"
                )
        else:
            try:
                results = await asyncio.to_thread(
                    memory_indexer.retrieve,
                    message,
                    settings=runtime.retrieval.memory,
                )
            except Exception:
                return RetrievalEnvelope(
                    rag_mode=True, degradation="index_unavailable"
                )
        results = RetrievalOrchestrator._bound_results(results)
        rag_context = RetrievalOrchestrator._format_context(results)
        return RetrievalEnvelope(
            rag_mode=True,
            results=results,
            rag_context=rag_context,
            degradation=RetrievalOrchestrator._degradation(memory_indexer),
        )
