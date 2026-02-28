from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from config import RetrievalDomainConfig
from graph.memory_indexer import MemoryIndexer
from tools.search_knowledge_tool import SearchKnowledgeTool


def test_memory_indexer_honors_top_k_and_chunk_settings(tmp_path: Path):
    (tmp_path / "memory").mkdir(parents=True, exist_ok=True)
    (tmp_path / "storage").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config.json").write_text('{"retrieval":{"memory":{"top_k":3}}}\n', encoding="utf-8")
    (tmp_path / "memory" / "MEMORY.md").write_text(
        "alpha one\nbeta two\nalpha three\nalpha four\n",
        encoding="utf-8",
    )

    settings = RetrievalDomainConfig(
        top_k=1,
        semantic_weight=0.0,
        lexical_weight=1.0,
        chunk_size=12,
        chunk_overlap=2,
    )
    indexer = MemoryIndexer(tmp_path, config_base_dir=tmp_path)
    indexer.rebuild_index(settings=settings)
    json_index = tmp_path / "storage" / "memory_index" / "index.json"
    sqlite_index = tmp_path / "storage" / "retrieval.db"
    if json_index.exists():
        payload = json.loads(json_index.read_text(encoding="utf-8"))
        assert payload["chunk_size"] == 64  # runtime sanitizer lower-bound
        assert payload["chunk_overlap"] == 2
    else:
        with sqlite3.connect(sqlite_index) as conn:
            row = conn.execute(
                "SELECT chunk_size, chunk_overlap FROM index_meta WHERE domain = 'memory'"
            ).fetchone()
        assert row is not None
        assert int(row[0]) == 64
        assert int(row[1]) == 2

    rows = indexer.retrieve("alpha", settings=settings)
    assert len(rows) == 1


def test_search_knowledge_tool_honors_runtime_tuning(tmp_path: Path):
    (tmp_path / "knowledge").mkdir(parents=True, exist_ok=True)
    (tmp_path / "storage").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "knowledge" / "guide.md").write_text(
        "alpha section one\n\nbeta section two\n\nalpha section three\n",
        encoding="utf-8",
    )

    tool = SearchKnowledgeTool(
        root_dir=tmp_path,
        config_base_dir=tmp_path,
        default_top_k=1,
        semantic_weight=0.0,
        lexical_weight=1.0,
        chunk_size=64,
        chunk_overlap=8,
    )
    result = tool.run({"query": "alpha"}, context=None)  # type: ignore[arg-type]
    assert result.ok is True
    assert len(result.data["results"]) == 1

    json_index = tmp_path / "storage" / "knowledge_index" / "index.json"
    sqlite_index = tmp_path / "storage" / "retrieval.db"
    if json_index.exists():
        index_payload = json.loads(json_index.read_text(encoding="utf-8"))
        assert index_payload["chunk_size"] == 64
        assert index_payload["chunk_overlap"] == 8
    else:
        with sqlite3.connect(sqlite_index) as conn:
            row = conn.execute(
                "SELECT chunk_size, chunk_overlap FROM index_meta WHERE domain = 'knowledge'"
            ).fetchone()
        assert row is not None
        assert int(row[0]) == 64
        assert int(row[1]) == 8
