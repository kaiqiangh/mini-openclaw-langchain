from __future__ import annotations

import os
import sqlite3
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Deque


@dataclass
class RateLimitDecision:
    allowed: bool
    retry_after_seconds: int


class LocalCoordinator:
    def acquire_stream_lock(self, key: str, owner: str, ttl_seconds: int) -> bool:
        raise NotImplementedError

    def release_stream_lock(self, key: str, owner: str) -> None:
        raise NotImplementedError

    def check_rate_limit(self, key: str, limit: int, window_seconds: int) -> RateLimitDecision:
        raise NotImplementedError


class InMemoryCoordinator(LocalCoordinator):
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._stream_locks: dict[str, tuple[str, float]] = {}
        self._rate_buckets: dict[str, Deque[float]] = defaultdict(deque)

    def _purge_stream_if_expired(self, key: str, now: float) -> None:
        current = self._stream_locks.get(key)
        if current is None:
            return
        _, expires_at = current
        if expires_at <= now:
            self._stream_locks.pop(key, None)

    def acquire_stream_lock(self, key: str, owner: str, ttl_seconds: int) -> bool:
        now = time.time()
        expires_at = now + max(5, int(ttl_seconds))
        with self._lock:
            self._purge_stream_if_expired(key, now)
            current = self._stream_locks.get(key)
            if current is None:
                self._stream_locks[key] = (owner, expires_at)
                return True
            current_owner, _ = current
            if current_owner == owner:
                self._stream_locks[key] = (owner, expires_at)
                return True
            return False

    def release_stream_lock(self, key: str, owner: str) -> None:
        with self._lock:
            current = self._stream_locks.get(key)
            if current is None:
                return
            current_owner, _ = current
            if current_owner == owner:
                self._stream_locks.pop(key, None)

    def check_rate_limit(self, key: str, limit: int, window_seconds: int) -> RateLimitDecision:
        now = time.time()
        window = max(1, int(window_seconds))
        with self._lock:
            bucket = self._rate_buckets[key]
            while bucket and now - bucket[0] > window:
                bucket.popleft()
            if len(bucket) >= max(1, int(limit)):
                oldest = bucket[0]
                retry_after = max(1, int((oldest + window) - now))
                return RateLimitDecision(allowed=False, retry_after_seconds=retry_after)
            bucket.append(now)
        return RateLimitDecision(allowed=True, retry_after_seconds=0)


class SQLiteCoordinator(LocalCoordinator):
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _ensure_schema(self) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS stream_locks (
                        lock_key TEXT PRIMARY KEY,
                        owner TEXT NOT NULL,
                        expires_at REAL NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS rate_events (
                        bucket_key TEXT NOT NULL,
                        ts REAL NOT NULL
                    )
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_rate_events_key_ts ON rate_events(bucket_key, ts)"
                )
                conn.commit()

    def acquire_stream_lock(self, key: str, owner: str, ttl_seconds: int) -> bool:
        now = time.time()
        expires_at = now + max(5, int(ttl_seconds))
        with self._lock:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    "DELETE FROM stream_locks WHERE lock_key = ? AND expires_at <= ?",
                    (key, now),
                )
                row = conn.execute(
                    "SELECT owner FROM stream_locks WHERE lock_key = ?",
                    (key,),
                ).fetchone()
                if row is None:
                    conn.execute(
                        "INSERT INTO stream_locks(lock_key, owner, expires_at) VALUES (?, ?, ?)",
                        (key, owner, expires_at),
                    )
                    conn.commit()
                    return True

                current_owner = str(row[0])
                if current_owner != owner:
                    conn.rollback()
                    return False

                conn.execute(
                    "UPDATE stream_locks SET expires_at = ? WHERE lock_key = ? AND owner = ?",
                    (expires_at, key, owner),
                )
                conn.commit()
                return True

    def release_stream_lock(self, key: str, owner: str) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    "DELETE FROM stream_locks WHERE lock_key = ? AND owner = ?",
                    (key, owner),
                )
                conn.commit()

    def check_rate_limit(self, key: str, limit: int, window_seconds: int) -> RateLimitDecision:
        now = time.time()
        window = max(1, int(window_seconds))
        min_ts = now - window
        with self._lock:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    "DELETE FROM rate_events WHERE bucket_key = ? AND ts < ?",
                    (key, min_ts),
                )
                rows = conn.execute(
                    "SELECT ts FROM rate_events WHERE bucket_key = ? ORDER BY ts ASC",
                    (key,),
                ).fetchall()
                limit_value = max(1, int(limit))
                if len(rows) >= limit_value:
                    oldest = float(rows[0][0])
                    retry_after = max(1, int((oldest + window) - now))
                    conn.commit()
                    return RateLimitDecision(allowed=False, retry_after_seconds=retry_after)

                conn.execute(
                    "INSERT INTO rate_events(bucket_key, ts) VALUES (?, ?)",
                    (key, now),
                )
                conn.commit()
                return RateLimitDecision(allowed=True, retry_after_seconds=0)


def build_local_coordinator(base_dir: Path) -> LocalCoordinator:
    backend = (os.getenv("CONTROL_BACKEND", "in_memory") or "in_memory").strip().lower()
    if backend == "sqlite":
        db_path_raw = (os.getenv("CONTROL_DB_PATH", "storage/control.db") or "storage/control.db").strip()
        db_path = Path(db_path_raw)
        if not db_path.is_absolute():
            db_path = (base_dir / db_path).resolve()
        return SQLiteCoordinator(db_path=db_path)
    return InMemoryCoordinator()
