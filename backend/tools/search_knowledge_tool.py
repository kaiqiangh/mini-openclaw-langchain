from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config import RetrievalStorageConfig, load_config, load_effective_runtime_config, load_runtime_config
from graph.embedding_client import EmbeddingClient, cosine_similarity
from graph.retrieval_store import RetrievalChunk, SQLiteRetrievalStore

from .base import ToolContext
from .contracts import ToolResult
from .path_guard import resolve_workspace_path
from .policy import PermissionLevel


@dataclass
class SearchKnowledgeTool:
    root_dir: Path
    config_base_dir: Path | None = None
    default_top_k: int = 3
    semantic_weight: float = 0.7
    lexical_weight: float = 0.3
    chunk_size: int = 400
    chunk_overlap: int = 80

    name: str = "search_knowledge_base"
    description: str = "Search local knowledge files with lexical scoring"
    permission_level: PermissionLevel = PermissionLevel.L0_READ

    @property
    def _index_dir(self) -> Path:
        return self.root_dir / "storage" / "knowledge_index"

    @property
    def _index_file(self) -> Path:
        return self._index_dir / "index.json"

    @staticmethod
    def _chunk(text: str, size: int, overlap: int) -> list[str]:
        if not text:
            return []
        chunks: list[str] = []
        step = max(1, size - overlap)
        for start in range(0, len(text), step):
            chunks.append(text[start : start + size])
        return chunks

    def _knowledge_digest(self, files: list[Path], *, chunk_size: int, chunk_overlap: int) -> str:
        hasher = hashlib.sha256()
        for file_path in sorted(files):
            stat = file_path.stat()
            hasher.update(str(file_path.relative_to(self.root_dir)).encode("utf-8"))
            hasher.update(str(stat.st_mtime_ns).encode("utf-8"))
            hasher.update(str(stat.st_size).encode("utf-8"))
        hasher.update(str(chunk_size).encode("utf-8"))
        hasher.update(str(chunk_overlap).encode("utf-8"))
        return hasher.hexdigest()

    def _build_index(self, files: list[Path], digest: str, *, chunk_size: int, chunk_overlap: int) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        for file_path in files:
            text = file_path.read_text(encoding="utf-8", errors="replace")
            for chunk in self._chunk(text, chunk_size, chunk_overlap):
                rows.append(
                    {
                        "source": str(file_path.relative_to(self.root_dir)),
                        "text": chunk,
                    }
                )

        config = load_config(self.config_base_dir or self.root_dir)
        provider = config.secrets.embedding_provider.value
        model = (
            config.secrets.embedding_model
            if provider == "openai"
            else config.secrets.google_embedding_model
        )

        embedding_error = ""
        vectors: list[list[float]] = []
        if rows:
            try:
                vectors = EmbeddingClient(config.secrets).embed_texts([row["text"] for row in rows])
            except Exception as exc:  # noqa: BLE001
                vectors = []
                embedding_error = str(exc)

        for idx, row in enumerate(rows):
            row["embedding"] = vectors[idx] if idx < len(vectors) else []

        return {
            "digest": digest,
            "chunk_size": chunk_size,
            "chunk_overlap": chunk_overlap,
            "embedding_provider": provider,
            "embedding_model": model,
            "embedding_error": embedding_error,
            "rows": rows,
        }

    def _resolve_storage_settings(self) -> RetrievalStorageConfig:
        config_base = self.config_base_dir or self.root_dir
        global_config = config_base / "config.json"
        agent_config = self.root_dir / "config.json"
        if global_config.exists() and agent_config.exists() and global_config.resolve() != agent_config.resolve():
            runtime = load_effective_runtime_config(global_config, agent_config)
        elif agent_config.exists():
            runtime = load_runtime_config(agent_config)
        else:
            runtime = load_config(config_base).runtime
        storage = runtime.retrieval.storage
        return RetrievalStorageConfig(
            engine=str(storage.engine).strip().lower() or "sqlite",
            db_path=str(storage.db_path).strip() or "storage/retrieval.db",
            fts_prefilter_k=max(1, int(storage.fts_prefilter_k)),
        )

    def _sqlite_store(self, storage: RetrievalStorageConfig) -> SQLiteRetrievalStore:
        return SQLiteRetrievalStore(root_dir=self.root_dir, db_path=storage.db_path)

    @staticmethod
    def _safe_int(value: object, fallback: int) -> int:
        try:
            return int(value)
        except Exception:
            return fallback

    def _migrate_json_to_sqlite(
        self,
        *,
        store: SQLiteRetrievalStore,
        payload: dict[str, Any],
        digest_fallback: str,
        chunk_size_fallback: int,
        chunk_overlap_fallback: int,
    ) -> bool:
        rows = payload.get("rows")
        if not isinstance(rows, list):
            return False
        digest = str(payload.get("digest", digest_fallback))
        chunk_size = max(64, self._safe_int(payload.get("chunk_size"), chunk_size_fallback))
        chunk_overlap = max(0, self._safe_int(payload.get("chunk_overlap"), chunk_overlap_fallback))
        provider = str(payload.get("embedding_provider", "openai"))
        model = str(payload.get("embedding_model", "text-embedding-3-small"))

        chunks: list[RetrievalChunk] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            source = str(row.get("source", "knowledge/unknown"))
            text = str(row.get("text", ""))
            embedding = row.get("embedding", [])
            parsed_embedding: list[float] = []
            if isinstance(embedding, list):
                for item in embedding:
                    try:
                        parsed_embedding.append(float(item))
                    except Exception:
                        continue
            chunks.append(RetrievalChunk(source=source, text=text, embedding=parsed_embedding))

        store.replace_domain_index(
            domain="knowledge",
            digest=digest,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            embedding_provider=provider,
            embedding_model=model,
            chunks=chunks,
        )
        return True

    def _ensure_sqlite_index(
        self,
        *,
        files: list[Path],
        chunk_size: int,
        chunk_overlap: int,
        storage: RetrievalStorageConfig,
    ) -> SQLiteRetrievalStore | None:
        try:
            store = self._sqlite_store(storage)
        except Exception:
            return None

        digest = self._knowledge_digest(files, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        meta = store.get_meta("knowledge")
        if meta is None and self._index_file.exists():
            try:
                payload = json.loads(self._index_file.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    self._migrate_json_to_sqlite(
                        store=store,
                        payload=payload,
                        digest_fallback=digest,
                        chunk_size_fallback=chunk_size,
                        chunk_overlap_fallback=chunk_overlap,
                    )
                    meta = store.get_meta("knowledge")
            except Exception:
                meta = None

        if meta is not None and str(meta.get("digest", "")) == digest:
            return store

        payload = self._build_index(files, digest, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        rows = payload.get("rows", [])
        if not isinstance(rows, list):
            rows = []
        chunks: list[RetrievalChunk] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            embedding = row.get("embedding", [])
            parsed_embedding: list[float] = []
            if isinstance(embedding, list):
                for item in embedding:
                    try:
                        parsed_embedding.append(float(item))
                    except Exception:
                        continue
            chunks.append(
                RetrievalChunk(
                    source=str(row.get("source", "knowledge/unknown")),
                    text=str(row.get("text", "")),
                    embedding=parsed_embedding,
                )
            )
        try:
            store.replace_domain_index(
                domain="knowledge",
                digest=digest,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                embedding_provider=str(payload.get("embedding_provider", "openai")),
                embedding_model=str(payload.get("embedding_model", "text-embedding-3-small")),
                chunks=chunks,
            )
            return store
        except Exception:
            return None

    def _load_or_rebuild_index(self, files: list[Path], *, chunk_size: int, chunk_overlap: int) -> dict[str, Any]:
        digest = self._knowledge_digest(files, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        if self._index_file.exists():
            payload = json.loads(self._index_file.read_text(encoding="utf-8"))
            if payload.get("digest") == digest:
                return payload

        self._index_dir.mkdir(parents=True, exist_ok=True)
        payload = self._build_index(files, digest, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        self._index_file.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
        return payload

    def run(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        _ = context
        started = time.monotonic()
        query = str(args.get("query", "")).strip().lower()
        top_k = max(1, int(args.get("top_k", self.default_top_k)))
        chunk_size = max(64, int(self.chunk_size))
        chunk_overlap = max(0, int(self.chunk_overlap))

        if not query:
            return ToolResult.failure(
                tool_name=self.name,
                code="E_INVALID_ARGS",
                message="Missing required 'query' argument",
                duration_ms=int((time.monotonic() - started) * 1000),
            )

        knowledge_dir = resolve_workspace_path(self.root_dir, "knowledge")
        files = [p for p in knowledge_dir.rglob("*") if p.is_file()]

        query_embedding: list[float] = []
        try:
            config = load_config(self.config_base_dir or self.root_dir)
            embedded = EmbeddingClient(config.secrets).embed_texts([query])
            if embedded:
                query_embedding = embedded[0]
        except Exception:
            query_embedding = []

        storage = self._resolve_storage_settings()
        if storage.engine == "sqlite":
            store = self._ensure_sqlite_index(
                files=files,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                storage=storage,
            )
            if store is not None:
                results = store.retrieve(
                    domain="knowledge",
                    query=query,
                    top_k=top_k,
                    fts_prefilter_k=storage.fts_prefilter_k,
                    semantic_weight=float(self.semantic_weight),
                    lexical_weight=float(self.lexical_weight),
                    query_embedding=query_embedding,
                )
                if results:
                    return ToolResult.success(
                        tool_name=self.name,
                        data={"query": query, "results": results},
                        duration_ms=int((time.monotonic() - started) * 1000),
                    )

        payload = self._load_or_rebuild_index(files, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        rows = payload.get("rows", [])
        if not isinstance(rows, list):
            rows = []

        terms = {term for term in query.split() if term}
        scored: list[tuple[float, str, str]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            text = str(row.get("text", ""))
            source = str(row.get("source", "knowledge/unknown"))
            lower = text.lower()
            lexical = float(sum(1 for term in terms if term in lower))
            vector = 0.0
            if query_embedding:
                vector = cosine_similarity(query_embedding, row.get("embedding", []))
            score = (vector * float(self.semantic_weight)) + (lexical * float(self.lexical_weight))
            if score > 0:
                snippet = text[:300].replace("\n", " ")
                scored.append((score, source, snippet))

        scored.sort(key=lambda item: item[0], reverse=True)
        results = [
            {
                "text": item[2],
                "score": item[0],
                "source": item[1],
            }
            for item in scored[:top_k]
        ]

        return ToolResult.success(
            tool_name=self.name,
            data={"query": query, "results": results},
            duration_ms=int((time.monotonic() - started) * 1000),
        )
