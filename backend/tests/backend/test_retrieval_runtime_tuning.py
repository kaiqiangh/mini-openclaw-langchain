from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

import tools.search_knowledge_tool as search_knowledge_module
from config import RetrievalDomainConfig
from graph.memory_indexer import MemoryIndexer
from tools.search_knowledge_tool import SearchKnowledgeTool


def test_memory_indexer_honors_top_k_and_chunk_settings(tmp_path: Path):
    (tmp_path / "memory").mkdir(parents=True, exist_ok=True)
    (tmp_path / "storage").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config.json").write_text(
        '{"retrieval":{"memory":{"top_k":3}}}\n', encoding="utf-8"
    )
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


def test_memory_indexer_normalizes_punctuation_in_lexical_queries(tmp_path: Path):
    (tmp_path / "memory").mkdir(parents=True, exist_ok=True)
    (tmp_path / "storage").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config.json").write_text(
        '{"retrieval":{"storage":{"engine":"json"}}}\n', encoding="utf-8"
    )
    (tmp_path / "memory" / "MEMORY.md").write_text(
        "BSC meme-token launch notes", encoding="utf-8"
    )
    settings = RetrievalDomainConfig(
        top_k=1,
        semantic_weight=0.0,
        lexical_weight=1.0,
        chunk_size=64,
        chunk_overlap=0,
    )
    indexer = MemoryIndexer(tmp_path, config_base_dir=tmp_path)

    rows = indexer.retrieve("meme-token", settings=settings)

    assert rows
    assert rows[0]["score"] == 2.0


def test_memory_indexer_async_retrieval_is_bounded_and_offloads_work(tmp_path: Path):
    (tmp_path / "memory").mkdir(parents=True, exist_ok=True)
    (tmp_path / "storage").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "memory" / "MEMORY.md").write_text(
        "\n".join(f"alpha {index}" for index in range(30)), encoding="utf-8"
    )
    indexer = MemoryIndexer(tmp_path, config_base_dir=tmp_path)
    settings = RetrievalDomainConfig(
        top_k=100,
        semantic_weight=0.0,
        lexical_weight=1.0,
        chunk_size=64,
        chunk_overlap=0,
    )

    rows = asyncio.run(indexer.aretrieve("alpha", settings=settings))

    assert len(rows) <= 20


def test_memory_indexer_does_not_return_stale_rows_while_rebuilding(tmp_path: Path, monkeypatch):
    (tmp_path / "memory").mkdir(parents=True, exist_ok=True)
    (tmp_path / "storage").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config.json").write_text(
        '{"retrieval":{"storage":{"engine":"sqlite"}}}\n', encoding="utf-8"
    )
    memory_file = tmp_path / "memory" / "MEMORY.md"
    memory_file.write_text("old fact", encoding="utf-8")
    settings = RetrievalDomainConfig(
        top_k=2, semantic_weight=0.0, lexical_weight=1.0, chunk_size=64, chunk_overlap=0
    )
    indexer = MemoryIndexer(tmp_path, config_base_dir=tmp_path)
    indexer.rebuild_index(settings=settings)
    memory_file.write_text("new fact", encoding="utf-8")
    monkeypatch.setattr(indexer, "schedule_rebuild", lambda **kwargs: indexer._set_status(state="building"))

    assert indexer.retrieve("old", settings=settings) == []
    assert indexer.status()["state"] == "building"


def test_memory_indexer_reports_failed_rebuild_without_raising(tmp_path: Path, monkeypatch):
    (tmp_path / "memory").mkdir(parents=True, exist_ok=True)
    (tmp_path / "storage").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config.json").write_text("{}\n", encoding="utf-8")
    indexer = MemoryIndexer(tmp_path, config_base_dir=tmp_path)
    monkeypatch.setattr(indexer, "_rebuild_index", lambda **kwargs: (_ for _ in ()).throw(OSError("index unavailable")))

    indexer.rebuild_index()

    assert indexer.status()["state"] == "failed"
    assert "index unavailable" in str(indexer.status()["last_error"])


def test_retrieval_orchestrator_degrades_when_indexer_fails():
    from config import RuntimeConfig
    from graph.retrieval_orchestrator import RetrievalOrchestrator

    class BrokenIndexer:
        def retrieve(self, *args, **kwargs):
            raise OSError("index unavailable")

    envelope = RetrievalOrchestrator.build_envelope(
        runtime=RuntimeConfig(rag_mode=True),
        memory_indexer=BrokenIndexer(),
        message="memory",
    )

    assert envelope.results == []
    assert envelope.degradation == "index_unavailable"


def test_retrieval_orchestrator_skips_malformed_rows():
    from config import RuntimeConfig
    from graph.retrieval_orchestrator import RetrievalOrchestrator

    class Indexer:
        def retrieve(self, *args, **kwargs):
            return [{"score": 1, "text": "valid"}, {"metadata": {"bad": True}}]

    envelope = RetrievalOrchestrator.build_envelope(
        runtime=RuntimeConfig(rag_mode=True),
        memory_indexer=Indexer(),
        message="memory",
    )

    assert len(envelope.results) == 1
    assert envelope.results[0]["text"] == "valid"


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
    assert result.data["results"] == []
    assert tool._build_thread is not None
    tool._build_thread.join(timeout=5)
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


def test_search_knowledge_build_bounds_bytes_and_chunks(tmp_path: Path, monkeypatch):
    (tmp_path / "knowledge").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config.json").write_text("{}\n", encoding="utf-8")
    first = tmp_path / "knowledge" / "first.md"
    second = tmp_path / "knowledge" / "second.md"
    first.write_bytes(b"a" * 6)
    second.write_bytes(b"b" * 6)

    class FakeEmbeddingClient:
        def __init__(self, secrets):
            _ = secrets

        def embed_texts(self, texts):
            return [[] for _ in texts]

    monkeypatch.setattr(search_knowledge_module, "EmbeddingClient", FakeEmbeddingClient)
    monkeypatch.setattr(search_knowledge_module, "MAX_KNOWLEDGE_FILE_BYTES", 6)
    monkeypatch.setattr(search_knowledge_module, "MAX_KNOWLEDGE_TOTAL_BYTES", 10)
    monkeypatch.setattr(search_knowledge_module, "MAX_KNOWLEDGE_CHUNKS", 3)

    tool = SearchKnowledgeTool(root_dir=tmp_path, config_base_dir=tmp_path)
    payload = tool._build_index(
        [first, second], "digest", chunk_size=4, chunk_overlap=0
    )

    rows = payload["rows"]
    assert len(rows) == 3
    assert [len(row["text"]) for row in rows] == [4, 2, 4]
    assert [row["source"] for row in rows] == [
        "knowledge/first.md",
        "knowledge/first.md",
        "knowledge/second.md",
    ]
