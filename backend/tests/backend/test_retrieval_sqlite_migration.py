from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from config import RetrievalDomainConfig
from graph.memory_indexer import MemoryIndexer
from tools.search_knowledge_tool import SearchKnowledgeTool


def test_memory_indexer_migrates_legacy_json_index_to_sqlite(tmp_path: Path):
    (tmp_path / "memory").mkdir(parents=True, exist_ok=True)
    (tmp_path / "storage" / "memory_index").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config.json").write_text(
        json.dumps(
            {
                "retrieval": {
                    "storage": {"engine": "sqlite", "db_path": "storage/retrieval.db"}
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "memory" / "MEMORY.md").write_text(
        "alpha one\nbeta two\nalpha three\n", encoding="utf-8"
    )

    settings = RetrievalDomainConfig(
        top_k=2, semantic_weight=0.0, lexical_weight=1.0, chunk_size=64, chunk_overlap=8
    )
    indexer = MemoryIndexer(tmp_path, config_base_dir=tmp_path)
    digest = indexer._memory_digest(  # type: ignore[attr-defined]
        (tmp_path / "memory" / "MEMORY.md").read_text(encoding="utf-8"),
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
    )
    legacy_payload = {
        "digest": digest,
        "chunk_size": settings.chunk_size,
        "chunk_overlap": settings.chunk_overlap,
        "chunks": ["alpha one", "beta two", "alpha three"],
        "embeddings": [[], [], []],
        "source": "memory/MEMORY.md",
        "embedding_provider": "openai",
        "embedding_model": "text-embedding-3-small",
    }
    (tmp_path / "storage" / "memory_index" / "index.json").write_text(
        json.dumps(legacy_payload) + "\n",
        encoding="utf-8",
    )

    rows = indexer.retrieve("alpha", settings=settings)
    assert rows
    assert rows[0]["source"] == "memory/MEMORY.md"

    with sqlite3.connect(tmp_path / "storage" / "retrieval.db") as conn:
        meta = conn.execute(
            "SELECT digest FROM index_meta WHERE domain = 'memory'"
        ).fetchone()
    assert meta is not None
    assert str(meta[0]) == digest


def test_search_knowledge_migrates_legacy_json_index_to_sqlite(tmp_path: Path):
    (tmp_path / "knowledge").mkdir(parents=True, exist_ok=True)
    (tmp_path / "storage" / "knowledge_index").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config.json").write_text(
        json.dumps(
            {
                "retrieval": {
                    "storage": {"engine": "sqlite", "db_path": "storage/retrieval.db"}
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "knowledge" / "guide.md").write_text(
        "alpha section\nbeta section\n", encoding="utf-8"
    )

    tool = SearchKnowledgeTool(
        root_dir=tmp_path,
        config_base_dir=tmp_path,
        default_top_k=2,
        semantic_weight=0.0,
        lexical_weight=1.0,
        chunk_size=64,
        chunk_overlap=8,
    )
    digest = tool._knowledge_digest([tmp_path / "knowledge" / "guide.md"], chunk_size=64, chunk_overlap=8)  # type: ignore[attr-defined]
    legacy_payload = {
        "digest": digest,
        "chunk_size": 64,
        "chunk_overlap": 8,
        "embedding_provider": "openai",
        "embedding_model": "text-embedding-3-small",
        "rows": [
            {"source": "knowledge/guide.md", "text": "alpha section", "embedding": []},
            {"source": "knowledge/guide.md", "text": "beta section", "embedding": []},
        ],
    }
    (tmp_path / "storage" / "knowledge_index" / "index.json").write_text(
        json.dumps(legacy_payload) + "\n",
        encoding="utf-8",
    )

    result = tool.run({"query": "alpha"}, context=None)  # type: ignore[arg-type]
    assert result.ok is True
    assert result.data["results"]

    with sqlite3.connect(tmp_path / "storage" / "retrieval.db") as conn:
        meta = conn.execute(
            "SELECT digest FROM index_meta WHERE domain = 'knowledge'"
        ).fetchone()
    assert meta is not None
    assert str(meta[0]) == digest
