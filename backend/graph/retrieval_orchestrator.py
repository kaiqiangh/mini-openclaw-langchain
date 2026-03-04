from __future__ import annotations

from typing import Any

from config import RuntimeConfig
from graph.agent_loop_types import RetrievalEnvelope


class RetrievalOrchestrator:
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
        rag_context = None
        if results:
            rag_context = "[Memory Retrieval Results]\n" + "\n".join(
                f"- ({item['score']}) {item['text']}" for item in results
            )
        return RetrievalEnvelope(
            rag_mode=True,
            results=results,
            rag_context=rag_context,
        )
