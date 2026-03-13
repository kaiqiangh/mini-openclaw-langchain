from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RetrievalEnvelope:
    rag_mode: bool
    results: list[dict[str, Any]] = field(default_factory=list)
    rag_context: str | None = None
