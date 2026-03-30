"""Tests for async I/O utilities."""
from pathlib import Path

import pytest

from utils.async_io import (
    read_jsonl,
    read_jsonl_reversed,
    append_jsonl,
    atomic_write,
    file_exists,
    read_text,
)


@pytest.mark.asyncio
async def test_read_jsonl_empty_file(tmp_path: Path):
    path = tmp_path / "test.jsonl"
    result = await read_jsonl(path)
    assert result == []


@pytest.mark.asyncio
async def test_read_jsonl_nonexistent(tmp_path: Path):
    path = tmp_path / "nonexistent.jsonl"
    result = await read_jsonl(path)
    assert result == []


@pytest.mark.asyncio
async def test_append_and_read_jsonl(tmp_path: Path):
    path = tmp_path / "test.jsonl"
    await append_jsonl(path, {"key": "value1"})
    await append_jsonl(path, {"key": "value2"})

    result = await read_jsonl(path)
    assert len(result) == 2
    assert result[0] == {"key": "value1"}
    assert result[1] == {"key": "value2"}


@pytest.mark.asyncio
async def test_read_jsonl_reversed(tmp_path: Path):
    path = tmp_path / "test.jsonl"
    await append_jsonl(path, {"order": 1})
    await append_jsonl(path, {"order": 2})
    await append_jsonl(path, {"order": 3})

    result = await read_jsonl_reversed(path)
    assert len(result) == 3
    assert result[0] == {"order": 3}
    assert result[2] == {"order": 1}


@pytest.mark.asyncio
async def test_append_jsonl_creates_dirs(tmp_path: Path):
    path = tmp_path / "sub" / "dir" / "test.jsonl"
    await append_jsonl(path, {"created": True})

    result = await read_jsonl(path)
    assert len(result) == 1
    assert result[0] == {"created": True}


@pytest.mark.asyncio
async def test_read_jsonl_skips_malformed(tmp_path: Path):
    import aiofiles

    path = tmp_path / "test.jsonl"
    async with aiofiles.open(str(path), mode="w", encoding="utf-8") as f:
        await f.write('{"valid": true}\n')
        await f.write("not json at all\n")
        await f.write("\n")
        await f.write('{"also_valid": true}\n')

    result = await read_jsonl(path)
    assert len(result) == 2
    assert result[0] == {"valid": True}
    assert result[1] == {"also_valid": True}


@pytest.mark.asyncio
async def test_atomic_write(tmp_path: Path):
    path = tmp_path / "test.txt"
    await atomic_write(path, "hello world")

    content = await read_text(path)
    assert content == "hello world"


@pytest.mark.asyncio
async def test_atomic_write_creates_dirs(tmp_path: Path):
    path = tmp_path / "deep" / "nested" / "test.txt"
    await atomic_write(path, "deep content")

    content = await read_text(path)
    assert content == "deep content"


@pytest.mark.asyncio
async def test_file_exists(tmp_path: Path):
    path = tmp_path / "exists.txt"
    assert await file_exists(path) is False

    await atomic_write(path, "exists")
    assert await file_exists(path) is True


@pytest.mark.asyncio
async def test_concurrent_appends(tmp_path: Path):
    """Multiple concurrent appends should all be recorded."""
    import asyncio

    path = tmp_path / "concurrent.jsonl"

    async def append_n(n: int):
        for i in range(10):
            await append_jsonl(path, {"n": n, "i": i})

    await asyncio.gather(*(append_n(i) for i in range(5)))

    result = await read_jsonl(path)
    assert len(result) == 50  # 5 tasks * 10 appends each
