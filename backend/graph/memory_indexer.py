from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from config import RetrievalDomainConfig, load_config
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
        self._last_digest: str | None = None

    @staticmethod
    def _sanitize_settings(settings: RetrievalDomainConfig) -> RetrievalDomainConfig:
        return RetrievalDomainConfig(
            top_k=max(1, int(settings.top_k)),
            semantic_weight=float(settings.semantic_weight),
            lexical_weight=float(settings.lexical_weight),
            chunk_size=max(64, int(settings.chunk_size)),
            chunk_overlap=max(0, int(settings.chunk_overlap)),
        )

    def _resolve_settings(self, settings: RetrievalDomainConfig | None) -> RetrievalDomainConfig:
        if settings is None:
            settings = load_config(self.config_base_dir).runtime.retrieval.memory
        return self._sanitize_settings(settings)

    @staticmethod
    def _chunk(text: str, *, size: int, overlap: int) -> list[str]:
        if not text:
            return []
        chunks: list[str] = []
        step = max(1, size - overlap)
        for start in range(0, len(text), step):
            chunks.append(text[start : start + size])
        return chunks

    @staticmethod
    def _memory_digest(text: str, *, chunk_size: int, chunk_overlap: int) -> str:
        payload = {
            "memory_hash": hashlib.md5(text.encode("utf-8")).hexdigest(),
            "chunk_size": chunk_size,
            "chunk_overlap": chunk_overlap,
        }
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def rebuild_index(self, settings: RetrievalDomainConfig | None = None) -> None:
        effective = self._resolve_settings(settings)
        self.index_dir.mkdir(parents=True, exist_ok=True)
        text = self.memory_file.read_text(encoding="utf-8") if self.memory_file.exists() else ""
        digest = self._memory_digest(
            text,
            chunk_size=effective.chunk_size,
            chunk_overlap=effective.chunk_overlap,
        )
        chunks = self._chunk(text, size=effective.chunk_size, overlap=effective.chunk_overlap)

        config = load_config(self.config_base_dir)
        provider = config.secrets.embedding_provider.value
        model = config.secrets.embedding_model if provider == "openai" else config.secrets.google_embedding_model

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
            "chunk_size": effective.chunk_size,
            "chunk_overlap": effective.chunk_overlap,
            "chunks": chunks,
            "source": "memory/MEMORY.md",
            "embedding_provider": provider,
            "embedding_model": model,
            "embeddings": embeddings,
            "embedding_error": embedding_error,
        }
        self.index_file.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
        self._last_digest = digest

    def _load_or_rebuild_index(self, settings: RetrievalDomainConfig) -> dict[str, object]:
        text = self.memory_file.read_text(encoding="utf-8") if self.memory_file.exists() else ""
        digest = self._memory_digest(
            text,
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
        )

        if self.index_file.exists():
            payload = json.loads(self.index_file.read_text(encoding="utf-8"))
            if payload.get("digest") == digest:
                self._last_digest = digest
                return payload

        self.rebuild_index(settings=settings)
        if self.index_file.exists():
            payload = json.loads(self.index_file.read_text(encoding="utf-8"))
            if payload.get("digest") == digest:
                return payload
        return {"chunks": [], "embeddings": []}

    def retrieve(
        self,
        query: str,
        top_k: int | None = None,
        *,
        settings: RetrievalDomainConfig | None = None,
    ) -> list[dict[str, object]]:
        effective = self._resolve_settings(settings)
        effective_top_k = max(1, int(top_k if top_k is not None else effective.top_k))
        payload = self._load_or_rebuild_index(effective)
        chunks: list[str] = payload.get("chunks", []) if isinstance(payload.get("chunks"), list) else []
        embeddings: list[list[float]] = payload.get("embeddings", []) if isinstance(payload.get("embeddings"), list) else []

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
            score = (vector * effective.semantic_weight) + (lexical * effective.lexical_weight)
            if score > 0:
                scored.append(RetrievalResult(text=chunk, score=score, source="memory/MEMORY.md"))

        scored.sort(key=lambda item: item.score, reverse=True)
        return [{"text": item.text, "score": item.score, "source": item.source} for item in scored[:effective_top_k]]
