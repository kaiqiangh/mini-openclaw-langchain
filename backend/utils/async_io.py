"""Async file I/O utilities using aiofiles."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import aiofiles
import aiofiles.os


async def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read all lines from a JSONL file asynchronously.

    Skips blank lines and malformed JSON entries.
    Returns list of parsed dicts.
    """
    if not await aiofiles.os.path.exists(str(path)):
        return []
    results: list[dict[str, Any]] = []
    async with aiofiles.open(str(path), mode="r", encoding="utf-8") as f:
        async for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                if isinstance(data, dict):
                    results.append(data)
            except json.JSONDecodeError:
                continue
    return results


async def read_jsonl_reversed(path: Path) -> list[dict[str, Any]]:
    """Read JSONL file in reverse order (newest first)."""
    all_lines = await read_jsonl(path)
    all_lines.reverse()
    return all_lines


async def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    """Append a single JSON record to a JSONL file.

    Creates parent directories if needed.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, default=str) + "\n"
    async with aiofiles.open(str(path), mode="a", encoding="utf-8") as f:
        await f.write(line)


async def atomic_write(path: Path, content: str) -> None:
    """Write content to a file atomically (write to temp, then rename).

    Prevents partial writes on crash.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path_str = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    tmp_path = Path(tmp_path_str)
    try:
        async with aiofiles.open(str(tmp_path), mode="w", encoding="utf-8") as f:
            await f.write(content)
        await aiofiles.os.rename(str(tmp_path), str(path))
    except Exception:
        try:
            await aiofiles.os.unlink(str(tmp_path))
        except OSError:
            pass
        raise


async def file_exists(path: Path) -> bool:
    """Check if a file exists asynchronously."""
    return await aiofiles.os.path.exists(str(path))


async def read_text(path: Path) -> str:
    """Read entire file content asynchronously."""
    async with aiofiles.open(str(path), mode="r", encoding="utf-8") as f:
        return await f.read()
