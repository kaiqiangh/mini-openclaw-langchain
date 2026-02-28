from __future__ import annotations

import json
from pathlib import Path

from graph.agent import AgentManager


def test_existing_agent_gets_retrieval_db_on_initialize(tmp_path: Path):
    base = tmp_path
    for rel in [
        "workspace",
        "memory",
        "knowledge",
        "skills",
        "storage",
        "workspaces/elon/workspace",
        "workspaces/elon/memory",
        "workspaces/elon/knowledge",
        "workspaces/elon/sessions/archive",
        "workspaces/elon/sessions/archived_sessions",
        "workspaces/elon/storage/memory_index",
    ]:
        (base / rel).mkdir(parents=True, exist_ok=True)

    for name in [
        "AGENTS.md",
        "SOUL.md",
        "IDENTITY.md",
        "USER.md",
        "HEARTBEAT.md",
        "BOOTSTRAP.md",
    ]:
        (base / "workspace" / name).write_text(f"# {name}\n", encoding="utf-8")
    (base / "memory" / "MEMORY.md").write_text("default memory\n", encoding="utf-8")
    (base / "SKILLS_SNAPSHOT.md").write_text(
        "<available_skills></available_skills>\n", encoding="utf-8"
    )

    (base / "config.json").write_text(
        json.dumps(
            {
                "retrieval": {
                    "storage": {
                        "engine": "sqlite",
                        "db_path": "storage/retrieval.db",
                        "fts_prefilter_k": 50,
                    }
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )

    # Existing legacy agent with JSON index only.
    (base / "workspaces" / "elon" / "workspace" / "SOUL.md").write_text(
        "# SOUL\n", encoding="utf-8"
    )
    (base / "workspaces" / "elon" / "memory" / "MEMORY.md").write_text(
        "hello from elon\n", encoding="utf-8"
    )
    (base / "workspaces" / "elon" / "config.json").write_text("{}\n", encoding="utf-8")
    (
        base / "workspaces" / "elon" / "storage" / "memory_index" / "index.json"
    ).write_text(
        json.dumps(
            {
                "digest": "legacy",
                "chunk_size": 64,
                "chunk_overlap": 8,
                "chunks": ["hello from elon"],
                "embeddings": [[]],
                "source": "memory/MEMORY.md",
                "embedding_provider": "openai",
                "embedding_model": "text-embedding-3-small",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    manager = AgentManager()
    manager.initialize(base)

    assert (base / "workspaces" / "elon" / "storage" / "retrieval.db").exists()


def test_existing_agent_root_memory_is_migrated_to_canonical_path(tmp_path: Path):
    base = tmp_path
    for rel in [
        "workspace",
        "memory",
        "knowledge",
        "skills",
        "storage",
        "workspaces/elon/workspace",
        "workspaces/elon/memory",
        "workspaces/elon/knowledge",
        "workspaces/elon/sessions/archive",
        "workspaces/elon/sessions/archived_sessions",
    ]:
        (base / rel).mkdir(parents=True, exist_ok=True)

    for name in [
        "AGENTS.md",
        "SOUL.md",
        "IDENTITY.md",
        "USER.md",
        "HEARTBEAT.md",
        "BOOTSTRAP.md",
    ]:
        (base / "workspace" / name).write_text(f"# {name}\n", encoding="utf-8")
    (base / "memory" / "MEMORY.md").write_text("default memory\n", encoding="utf-8")
    (base / "SKILLS_SNAPSHOT.md").write_text(
        "<available_skills></available_skills>\n", encoding="utf-8"
    )
    (base / "config.json").write_text("{}\n", encoding="utf-8")

    legacy_text = "legacy root memory content\n"
    (base / "workspaces" / "elon" / "MEMORY.md").write_text(
        legacy_text, encoding="utf-8"
    )
    (base / "workspaces" / "elon" / "memory" / "MEMORY.md").write_text(
        "# MEMORY\n\n- Keep this file concise.\n- Store stable preferences and long-lived context only.\n",
        encoding="utf-8",
    )
    (base / "workspaces" / "elon" / "config.json").write_text("{}\n", encoding="utf-8")

    manager = AgentManager()
    manager.initialize(base)

    canonical = base / "workspaces" / "elon" / "memory" / "MEMORY.md"
    assert canonical.read_text(encoding="utf-8") == legacy_text
