from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config import load_config
from graph.embedding_client import EmbeddingClient, cosine_similarity

from .base import ToolContext
from .contracts import ToolResult
from .path_guard import resolve_workspace_path
from .policy import PermissionLevel


@dataclass
class SearchKnowledgeTool:
    root_dir: Path
    config_base_dir: Path | None = None
    default_top_k: int = 3

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
    def _chunk(text: str, size: int = 400, overlap: int = 80) -> list[str]:
        if not text:
            return []
        chunks: list[str] = []
        step = max(1, size - overlap)
        for start in range(0, len(text), step):
            chunks.append(text[start : start + size])
        return chunks

    def _knowledge_digest(self, files: list[Path]) -> str:
        hasher = hashlib.sha256()
        for file_path in sorted(files):
            stat = file_path.stat()
            hasher.update(str(file_path.relative_to(self.root_dir)).encode("utf-8"))
            hasher.update(str(stat.st_mtime_ns).encode("utf-8"))
            hasher.update(str(stat.st_size).encode("utf-8"))
        return hasher.hexdigest()

    def _build_index(self, files: list[Path], digest: str) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        for file_path in files:
            text = file_path.read_text(encoding="utf-8", errors="replace")
            for chunk in self._chunk(text):
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
            "embedding_provider": provider,
            "embedding_model": model,
            "embedding_error": embedding_error,
            "rows": rows,
        }

    def _load_or_rebuild_index(self, files: list[Path]) -> dict[str, Any]:
        digest = self._knowledge_digest(files)
        if self._index_file.exists():
            payload = json.loads(self._index_file.read_text(encoding="utf-8"))
            if payload.get("digest") == digest:
                return payload

        self._index_dir.mkdir(parents=True, exist_ok=True)
        payload = self._build_index(files, digest)
        self._index_file.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
        return payload

    def run(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        _ = context
        started = time.monotonic()
        query = str(args.get("query", "")).strip().lower()
        top_k = int(args.get("top_k", self.default_top_k))

        if not query:
            return ToolResult.failure(
                tool_name=self.name,
                code="E_INVALID_ARGS",
                message="Missing required 'query' argument",
                duration_ms=int((time.monotonic() - started) * 1000),
            )

        knowledge_dir = resolve_workspace_path(self.root_dir, "knowledge")
        files = [p for p in knowledge_dir.rglob("*") if p.is_file()]
        payload = self._load_or_rebuild_index(files)
        rows = payload.get("rows", [])
        if not isinstance(rows, list):
            rows = []

        query_embedding: list[float] = []
        try:
            config = load_config(self.config_base_dir or self.root_dir)
            embedded = EmbeddingClient(config.secrets).embed_texts([query])
            if embedded:
                query_embedding = embedded[0]
        except Exception:
            query_embedding = []

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
            score = (vector * 0.7) + (lexical * 0.3)
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
