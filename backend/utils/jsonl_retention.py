from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from utils.async_io import iter_jsonl_reversed


def trim_jsonl(path: Path, *, max_records: int, max_bytes: int = 0) -> None:
    """Keep the newest valid records without materializing the whole history."""
    if not path.exists():
        return
    limit = max(1, int(max_records))
    over_bytes = max_bytes > 0 and path.stat().st_size > max_bytes
    rows: list[dict[str, Any]] = []
    for row in iter_jsonl_reversed(path):
        rows.append(row)
        if len(rows) > limit:
            break
    if len(rows) <= limit and not over_bytes:
        return
    rows = rows[:limit]
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with open(fd, "w", encoding="utf-8", closefd=True) as handle:
            for row in reversed(rows):
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        tmp_path.replace(path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
