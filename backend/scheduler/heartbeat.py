from __future__ import annotations

import asyncio
import json
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from config import HeartbeatRuntimeConfig
from graph.agent import AgentManager
from graph.session_manager import SessionManager


@dataclass
class HeartbeatRun:
    timestamp_ms: int
    status: str
    timezone: str
    details: dict[str, Any]
    started_at_ms: int | None = None
    finished_at_ms: int | None = None
    duration_ms: int | None = None
    schedule_lag_ms: int | None = None


class HeartbeatScheduler:
    def __init__(
        self,
        *,
        base_dir: Path,
        config: HeartbeatRuntimeConfig,
        agent_manager: AgentManager,
        session_manager: SessionManager,
        agent_id: str = "default",
    ) -> None:
        self.base_dir = base_dir
        self.config = config
        self.agent_manager = agent_manager
        self.session_manager = session_manager
        self.agent_id = agent_id
        self.audit_file = base_dir / "storage" / "heartbeat_runs.jsonl"
        self.prompt_file = base_dir / "workspace" / "HEARTBEAT.md"
        self._file_lock = threading.RLock()
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    def _zone(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.config.timezone)
        except ZoneInfoNotFoundError:
            return ZoneInfo("UTC")

    def _now_local(self) -> datetime:
        return datetime.now(self._zone())

    def _is_in_active_window(self, now: datetime) -> bool:
        start = int(self.config.active_start_hour) % 24
        end = int(self.config.active_end_hour) % 24
        hour = now.hour
        if start == end:
            return True
        if start < end:
            return start <= hour < end
        return hour >= start or hour < end

    def _read_prompt(self) -> str:
        if not self.prompt_file.exists():
            return "Run a heartbeat check. Reply exactly HEARTBEAT_OK when healthy."
        return self.prompt_file.read_text(encoding="utf-8", errors="replace").strip()

    @staticmethod
    def _normalize_prompt(raw_prompt: str) -> str:
        lines: list[str] = []
        for raw_line in raw_prompt.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            lines.append(line)
        return "\n".join(lines).strip()

    def _write_run(self, row: HeartbeatRun) -> None:
        with self._file_lock:
            self.audit_file.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "timestamp_ms": row.timestamp_ms,
                "status": row.status,
                "timezone": row.timezone,
                "details": row.details,
                "started_at_ms": row.started_at_ms,
                "finished_at_ms": row.finished_at_ms,
                "duration_ms": row.duration_ms,
                "schedule_lag_ms": row.schedule_lag_ms,
            }
            with self.audit_file.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def query_runs(
        self, *, limit: int = 100, since_ms: int | None = None
    ) -> list[dict[str, Any]]:
        max_rows = max(1, int(limit))
        with self._file_lock:
            if not self.audit_file.exists():
                return []
            lines = [
                line
                for line in self.audit_file.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        rows: list[dict[str, Any]] = []
        for line in reversed(lines):
            try:
                value = json.loads(line)
            except Exception:
                continue
            if isinstance(value, dict):
                if since_ms is not None:
                    observed_ts = int(
                        value.get("finished_at_ms")
                        or value.get("timestamp_ms")
                        or value.get("started_at_ms")
                        or 0
                    )
                    if observed_ts and observed_ts < since_ms:
                        continue
                rows.append(value)
                if len(rows) >= max_rows:
                    break
        return rows

    async def _tick_once(self) -> None:
        started_ts = time.time()
        now = self._now_local()
        if not self._is_in_active_window(now):
            finished_ts = time.time()
            self._write_run(
                HeartbeatRun(
                    timestamp_ms=int(finished_ts * 1000),
                    status="skipped_outside_window",
                    timezone=self.config.timezone,
                    started_at_ms=int(started_ts * 1000),
                    finished_at_ms=int(finished_ts * 1000),
                    duration_ms=max(0, int((finished_ts - started_ts) * 1000)),
                    details={
                        "active_start_hour": self.config.active_start_hour,
                        "active_end_hour": self.config.active_end_hour,
                        "local_hour": now.hour,
                    },
                )
            )
            return

        prompt = self._normalize_prompt(self._read_prompt())
        if not prompt:
            finished_ts = time.time()
            self._write_run(
                HeartbeatRun(
                    timestamp_ms=int(finished_ts * 1000),
                    status="skipped_no_prompt",
                    timezone=self.config.timezone,
                    started_at_ms=int(started_ts * 1000),
                    finished_at_ms=int(finished_ts * 1000),
                    duration_ms=max(0, int((finished_ts - started_ts) * 1000)),
                    details={"session_id": self.config.session_id},
                )
            )
            return
        repository = self.agent_manager.get_session_repository(self.agent_id)
        snapshot = await repository.load_snapshot(
            agent_id=self.agent_id,
            session_id=self.config.session_id,
            include_live=False,
            create_if_missing=True,
        )

        try:
            result = await self.agent_manager.run_once(
                message=prompt,
                history=[],
                session_id=self.config.session_id,
                is_first_turn=len(snapshot.messages) == 0,
                output_format="text",
                trigger_type="heartbeat",
                agent_id=self.agent_id,
            )
            text = str(result.get("text", "")).strip()
            suppressed = text == "HEARTBEAT_OK"
            run_id = str(result.get("run_id", "")).strip()

            finished_ts = time.time()
            self._write_run(
                HeartbeatRun(
                    timestamp_ms=int(finished_ts * 1000),
                    status="ok",
                    timezone=self.config.timezone,
                    started_at_ms=int(started_ts * 1000),
                    finished_at_ms=int(finished_ts * 1000),
                    duration_ms=max(0, int((finished_ts - started_ts) * 1000)),
                    details={
                        "run_id": run_id or None,
                        "session_id": self.config.session_id,
                        "suppressed": suppressed,
                        "response_preview": text[:200],
                    },
                )
            )
        except Exception as exc:  # noqa: BLE001
            finished_ts = time.time()
            self._write_run(
                HeartbeatRun(
                    timestamp_ms=int(finished_ts * 1000),
                    status="error",
                    timezone=self.config.timezone,
                    started_at_ms=int(started_ts * 1000),
                    finished_at_ms=int(finished_ts * 1000),
                    duration_ms=max(0, int((finished_ts - started_ts) * 1000)),
                    details={"error": str(exc)},
                )
            )

    async def run(self) -> None:
        while not self._stop_event.is_set():
            await self._tick_once()
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=max(30, int(self.config.interval_seconds)),
                )
            except asyncio.TimeoutError:
                continue

    def start(self) -> None:
        if self._task is not None or not self.config.enabled:
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self.run(), name="heartbeat-scheduler")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop_event.set()
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
