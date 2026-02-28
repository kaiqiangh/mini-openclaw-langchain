from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from graph.embedding_client import cosine_similarity

SCHEMA_VERSION = 1
_LOCK_REGISTRY_GUARD = threading.Lock()
_DB_LOCKS: dict[str, threading.RLock] = {}
_FTS_TOKEN = re.compile(r"[A-Za-z0-9_]+")


def _lock_for(path: Path) -> threading.RLock:
    key = str(path.resolve())
    with _LOCK_REGISTRY_GUARD:
        lock = _DB_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _DB_LOCKS[key] = lock
        return lock


def _as_embedding(value: str) -> list[float]:
    try:
        payload = json.loads(value)
    except Exception:
        return []
    if not isinstance(payload, list):
        return []
    rows: list[float] = []
    for item in payload:
        try:
            rows.append(float(item))
        except Exception:
            continue
    return rows


@dataclass
class RetrievalChunk:
    source: str
    text: str
    embedding: list[float]


class SQLiteRetrievalStore:
    def __init__(self, *, root_dir: Path, db_path: str) -> None:
        raw = Path(db_path)
        if raw.is_absolute():
            self.db_file = raw
        else:
            self.db_file = (root_dir / raw).resolve()
        self._lock = _lock_for(self.db_file)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_file, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _ensure_schema(self) -> None:
        with self._lock:
            self.db_file.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS index_meta (
                        domain TEXT PRIMARY KEY,
                        digest TEXT NOT NULL,
                        chunk_size INTEGER NOT NULL,
                        chunk_overlap INTEGER NOT NULL,
                        embedding_provider TEXT NOT NULL,
                        embedding_model TEXT NOT NULL,
                        updated_ms INTEGER NOT NULL,
                        schema_version INTEGER NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS chunks (
                        id INTEGER PRIMARY KEY,
                        domain TEXT NOT NULL,
                        source TEXT NOT NULL,
                        chunk_text TEXT NOT NULL,
                        embedding_json TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_chunks_domain ON chunks(domain)"
                )
                conn.execute(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(chunk_text)"
                )
                conn.commit()

    def get_meta(self, domain: str) -> dict[str, Any] | None:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT domain, digest, chunk_size, chunk_overlap, embedding_provider, embedding_model, updated_ms, schema_version
                    FROM index_meta
                    WHERE domain = ?
                    """,
                    (domain,),
                ).fetchone()
        if row is None:
            return None
        return dict(row)

    def _delete_domain_rows(self, conn: sqlite3.Connection, domain: str) -> None:
        ids = [
            row[0]
            for row in conn.execute(
                "SELECT id FROM chunks WHERE domain = ?", (domain,)
            ).fetchall()
        ]
        for chunk_id in ids:
            conn.execute("DELETE FROM chunks_fts WHERE rowid = ?", (chunk_id,))
        conn.execute("DELETE FROM chunks WHERE domain = ?", (domain,))

    def replace_domain_index(
        self,
        *,
        domain: str,
        digest: str,
        chunk_size: int,
        chunk_overlap: int,
        embedding_provider: str,
        embedding_model: str,
        chunks: list[RetrievalChunk],
    ) -> None:
        updated_ms = int(time.time() * 1000)
        with self._lock:
            with self._connect() as conn:
                self._delete_domain_rows(conn, domain)
                for chunk in chunks:
                    cursor = conn.execute(
                        """
                        INSERT INTO chunks(domain, source, chunk_text, embedding_json)
                        VALUES (?, ?, ?, ?)
                        """,
                        (
                            domain,
                            chunk.source,
                            chunk.text,
                            json.dumps(chunk.embedding, ensure_ascii=True),
                        ),
                    )
                    row_id_raw = cursor.lastrowid
                    if row_id_raw is None:
                        raise RuntimeError("SQLite insert returned no rowid")
                    row_id = int(row_id_raw)
                    conn.execute(
                        "INSERT INTO chunks_fts(rowid, chunk_text) VALUES (?, ?)",
                        (row_id, chunk.text),
                    )
                conn.execute(
                    """
                    INSERT INTO index_meta(
                        domain, digest, chunk_size, chunk_overlap, embedding_provider, embedding_model, updated_ms, schema_version
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(domain) DO UPDATE SET
                        digest=excluded.digest,
                        chunk_size=excluded.chunk_size,
                        chunk_overlap=excluded.chunk_overlap,
                        embedding_provider=excluded.embedding_provider,
                        embedding_model=excluded.embedding_model,
                        updated_ms=excluded.updated_ms,
                        schema_version=excluded.schema_version
                    """,
                    (
                        domain,
                        digest,
                        int(chunk_size),
                        int(chunk_overlap),
                        embedding_provider,
                        embedding_model,
                        updated_ms,
                        SCHEMA_VERSION,
                    ),
                )
                conn.commit()

    @staticmethod
    def _fts_query(query: str) -> str:
        tokens = _FTS_TOKEN.findall(query)
        if not tokens:
            return ""
        deduped: list[str] = []
        seen: set[str] = set()
        for token in tokens[:24]:
            lowered = token.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            deduped.append(f'"{lowered}"')
        return " OR ".join(deduped)

    def _candidate_rows(
        self, *, domain: str, query: str, limit: int
    ) -> list[sqlite3.Row]:
        max_rows = max(1, int(limit))
        fts_query = self._fts_query(query)
        with self._lock:
            with self._connect() as conn:
                if fts_query:
                    try:
                        rows = conn.execute(
                            """
                            SELECT c.id, c.source, c.chunk_text, c.embedding_json, bm25(chunks_fts) AS rank
                            FROM chunks_fts
                            JOIN chunks c ON c.id = chunks_fts.rowid
                            WHERE c.domain = ? AND chunks_fts MATCH ?
                            ORDER BY rank
                            LIMIT ?
                            """,
                            (domain, fts_query, max_rows),
                        ).fetchall()
                    except sqlite3.OperationalError:
                        rows = []
                else:
                    rows = []

                if rows:
                    return rows
                return conn.execute(
                    """
                    SELECT id, source, chunk_text, embedding_json
                    FROM chunks
                    WHERE domain = ?
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (domain, max_rows),
                ).fetchall()

    def retrieve(
        self,
        *,
        domain: str,
        query: str,
        top_k: int,
        fts_prefilter_k: int,
        semantic_weight: float,
        lexical_weight: float,
        query_embedding: list[float],
    ) -> list[dict[str, Any]]:
        rows = self._candidate_rows(
            domain=domain, query=query, limit=max(top_k, fts_prefilter_k)
        )
        terms = {item for item in query.lower().split() if item}
        scored: list[tuple[float, str, str]] = []
        for row in rows:
            text = str(row["chunk_text"])
            source = str(row["source"])
            lexical = float(sum(1 for term in terms if term in text.lower()))
            vector = 0.0
            if query_embedding:
                embedding = _as_embedding(str(row["embedding_json"]))
                if embedding:
                    vector = cosine_similarity(query_embedding, embedding)
            score = (vector * semantic_weight) + (lexical * lexical_weight)
            if score > 0:
                scored.append((score, source, text))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            {"text": item[2], "score": item[0], "source": item[1]}
            for item in scored[: max(1, int(top_k))]
        ]
