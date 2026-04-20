from __future__ import annotations

from pathlib import Path

from tools.base import ToolContext
from tools.read_files_tool import ReadFilesTool


def test_read_files_lists_directory_entries(tmp_path: Path):
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir(parents=True)
    (memory_dir / "MEMORY.md").write_text("# MEMORY\n", encoding="utf-8")
    (memory_dir / "notes.md").write_text("notes\n", encoding="utf-8")

    tool = ReadFilesTool(root_dir=tmp_path)
    context = ToolContext(workspace_root=tmp_path, trigger_type="chat")

    result = tool.run({"path": "memory/"}, context)

    assert result.ok is True
    item = result.data["results"][0]
    assert item["ok"] is True
    assert item["kind"] == "directory"
    assert [entry["path"] for entry in item["entries"]] == [
        "memory/MEMORY.md",
        "memory/notes.md",
    ]
    assert "MEMORY.md" in item["content"]
    assert "notes.md" in item["content"]
