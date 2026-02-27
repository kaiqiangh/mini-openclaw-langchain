from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from config import load_config
from graph.embedding_client import EmbeddingClient, cosine_similarity

@dataclass
class RetrievalResult:
    text: str
    score: float
    source: str


class MemoryIndexer:
    def __init__(self, base_dir: Path, config_base_dir: Path | None = None) -> None:
        self.base_dir = base_dir
        self.config_base_dir = config_base_dir or base_dir
        self.memory_file = base_dir / "memory" / "MEMORY.md"
        self.index_dir = base_dir / "storage" / "memory_index"
        self.index_file = self.index_dir / "index.json"
        self._last_hash: str | None = None

    def _chunk(self, text: str, size: int = 256, overlap: int = 32) -> list[str]:
        if not text:
            return []
        chunks: list[str] = []
        step = max(1, size - overlap)
        for start in range(0, len(text), step):
            chunks.append(text[start : start + size])
        return chunks

    def rebuild_index(self) -> None:
        self.index_dir.mkdir(parents=True, exist_ok=True)
        text = self.memory_file.read_text(encoding="utf-8") if self.memory_file.exists() else ""
        digest = hashlib.md5(text.encode("utf-8")).hexdigest()
        chunks = self._chunk(text)
        config = load_config(self.config_base_dir)
        provider = config.secrets.embedding_provider.value
        model = (
            config.secrets.embedding_model
            if provider == "openai"
            else config.secrets.google_embedding_model
        )

        embeddings: list[list[float]] = []
        embedding_error = ""
        if chunks:
            try:
                embeddings = EmbeddingClient(config.secrets).embed_texts(chunks)
            except Exception as exc:  # noqa: BLE001
                embeddings = []
                embedding_error = str(exc)

        payload = {
            "digest": digest,
            "chunks": chunks,
            "source": "memory/MEMORY.md",
            "embedding_provider": provider,
            "embedding_model": model,
            "embeddings": embeddings,
            "embedding_error": embedding_error,
        }
        self.index_file.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
        self._last_hash = digest

    def _maybe_rebuild(self) -> None:
        text = self.memory_file.read_text(encoding="utf-8") if self.memory_file.exists() else ""
        current_hash = hashlib.md5(text.encode("utf-8")).hexdigest()
        if not self.index_file.exists() or self._last_hash != current_hash:
            self.rebuild_index()

    def retrieve(self, query: str, top_k: int = 3) -> list[dict[str, object]]:
        self._maybe_rebuild()
        payload = json.loads(self.index_file.read_text(encoding="utf-8")) if self.index_file.exists() else {"chunks": []}
        chunks: list[str] = payload.get("chunks", [])
        embeddings: list[list[float]] = payload.get("embeddings", [])

        query_terms = {item for item in query.lower().split() if item}
        query_embedding: list[float] = []
        try:
            config = load_config(self.config_base_dir)
            embedded = EmbeddingClient(config.secrets).embed_texts([query])
            if embedded:
                query_embedding = embedded[0]
        except Exception:
            query_embedding = []

        scored: list[RetrievalResult] = []
        for idx, chunk in enumerate(chunks):
            lower = chunk.lower()
            lexical = float(sum(1 for term in query_terms if term in lower))
            vector = 0.0
            if query_embedding and idx < len(embeddings):
                vector = cosine_similarity(query_embedding, embeddings[idx])
            # Favor semantic similarity, with lexical tie-breaker.
            score = (vector * 0.7) + (lexical * 0.3)
            if score > 0:
                scored.append(RetrievalResult(text=chunk, score=score, source="memory/MEMORY.md"))

        scored.sort(key=lambda item: item.score, reverse=True)
        return [{"text": item.text, "score": item.score, "source": item.source} for item in scored[:top_k]]
