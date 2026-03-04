from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RetrievalEnvelope:
    rag_mode: bool
    results: list[dict[str, Any]] = field(default_factory=list)
    rag_context: str | None = None


@dataclass
class StreamLoopState:
    pending_new_response: bool = False
    final_tokens: list[str] = field(default_factory=list)
    fallback_final_text: str = ""
    token_source: str | None = None
    latest_model_snapshot: str = ""
    emitted_reasoning: set[str] = field(default_factory=set)
    emitted_agent_update: bool = False
