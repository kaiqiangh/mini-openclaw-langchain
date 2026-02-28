from __future__ import annotations

import asyncio
import json
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from config import CronRuntimeConfig
from graph.agent import AgentManager
from graph.session_manager import SessionManager


ScheduleType = Literal["at", "every", "cron"]

_LOCK_REGISTRY_GUARD = threading.Lock()
_FILE_LOCKS: dict[str, threading.RLock] = {}


def _lock_for(path: Path) -> threading.RLock:
    key = str(path.resolve())
    with _LOCK_REGISTRY_GUARD:
        lock = _FILE_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _FILE_LOCKS[key] = lock
        return lock


@dataclass
class CronJob:
    id: str
    name: str
    schedule_type: ScheduleType
    schedule: str
    prompt: str
    enabled: bool
    next_run_ts: float
    created_at: float
    updated_at: float
    last_run_ts: float = 0.0
    last_success_ts: float = 0.0
    failure_count: int = 0
    last_error: str = ""

    @staticmethod
    def from_dict(payload: dict[str, Any]) -> "CronJob":
        return CronJob(
            id=str(payload.get("id", "")),
            name=str(payload.get("name", "")),
            schedule_type=str(payload.get("schedule_type", "every")),  # type: ignore[arg-type]
            schedule=str(payload.get("schedule", "")),
            prompt=str(payload.get("prompt", "")),
            enabled=bool(payload.get("enabled", True)),
            next_run_ts=float(payload.get("next_run_ts", 0)),
            created_at=float(payload.get("created_at", 0)),
            updated_at=float(payload.get("updated_at", 0)),
            last_run_ts=float(payload.get("last_run_ts", 0)),
            last_success_ts=float(payload.get("last_success_ts", 0)),
            failure_count=int(payload.get("failure_count", 0)),
            last_error=str(payload.get("last_error", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _parse_iso_datetime(value: str, zone: ZoneInfo) -> datetime:
    text = value.strip()
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=zone)
    return parsed.astimezone(zone)


def _parse_cron_field(field: str, lower: int, upper: int) -> set[int]:
    values: set[int] = set()
    source = field.strip()
    if source == "*":
        return set(range(lower, upper + 1))

    for part in source.split(","):
        token = part.strip()
        if not token:
            continue
        if token.startswith("*/"):
            step = int(token[2:])
            if step <= 0:
                raise ValueError(f"Invalid step in cron field: {field}")
            values.update(range(lower, upper + 1, step))
            continue
        number = int(token)
        if number < lower or number > upper:
            raise ValueError(f"Cron field value out of range: {field}")
        values.add(number)

    if not values:
        raise ValueError(f"Invalid cron field: {field}")
    return values


def _cron_matches(expr: str, dt: datetime) -> bool:
    parts = expr.split()
    if len(parts) != 5:
        raise ValueError("Cron expression must have 5 fields: minute hour day month weekday")

    minutes = _parse_cron_field(parts[0], 0, 59)
    hours = _parse_cron_field(parts[1], 0, 23)
    days = _parse_cron_field(parts[2], 1, 31)
    months = _parse_cron_field(parts[3], 1, 12)
    weekdays = _parse_cron_field(parts[4], 0, 6)  # 0=Sun
    weekday = dt.isoweekday() % 7

    return (
        dt.minute in minutes
        and dt.hour in hours
        and dt.day in days
        and dt.month in months
        and weekday in weekdays
    )


def _next_cron_time(expr: str, after: datetime) -> datetime:
    cursor = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(60 * 24 * 366):
        if _cron_matches(expr, cursor):
            return cursor
        cursor += timedelta(minutes=1)
    raise ValueError(f"Unable to compute next run for cron expression: {expr}")


class CronScheduler:
    def __init__(
        self,
        *,
        base_dir: Path,
        config: CronRuntimeConfig,
        agent_manager: AgentManager,
        session_manager: SessionManager,
        agent_id: str = "default",
    ) -> None:
        self.base_dir = base_dir
        self.config = config
        self.agent_manager = agent_manager
        self.session_manager = session_manager
        self.agent_id = agent_id

        self.jobs_file = base_dir / "storage" / "cron_jobs.json"
        self.runs_file = base_dir / "storage" / "cron_runs.jsonl"
        self.failures_file = base_dir / "storage" / "cron_failures.jsonl"
        self._file_lock = _lock_for(self.jobs_file)
        self._async_lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    def _zone(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.config.timezone)
        except ZoneInfoNotFoundError:
            return ZoneInfo("UTC")

    def _load_jobs(self) -> list[CronJob]:
        with self._file_lock:
            if not self.jobs_file.exists():
                return []
            payload = json.loads(self.jobs_file.read_text(encoding="utf-8"))
            rows = payload.get("jobs", [])
            if not isinstance(rows, list):
                return []
            jobs: list[CronJob] = []
            for item in rows:
                if not isinstance(item, dict):
                    continue
                try:
                    jobs.append(CronJob.from_dict(item))
                except Exception:
                    continue
            return jobs

    def _save_jobs(self, jobs: list[CronJob]) -> None:
        with self._file_lock:
            self.jobs_file.parent.mkdir(parents=True, exist_ok=True)
            data = {"jobs": [job.to_dict() for job in jobs]}
            tmp = self.jobs_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            tmp.replace(self.jobs_file)

    def _write_jsonl(self, file_path: Path, payload: dict[str, Any]) -> None:
        with self._file_lock:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with file_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _trim_failures(self) -> None:
        with self._file_lock:
            if not self.failures_file.exists():
                return
            rows = self.failures_file.read_text(encoding="utf-8").splitlines()
            limit = max(1, int(self.config.failure_retention))
            if len(rows) <= limit:
                return
            self.failures_file.write_text("\n".join(rows[-limit:]) + "\n", encoding="utf-8")

    def _compute_next_run(self, job: CronJob, now_ts: float) -> float | None:
        zone = self._zone()
        now_dt = datetime.fromtimestamp(now_ts, tz=zone)

        if job.schedule_type == "at":
            return None
        if job.schedule_type == "every":
            interval = max(5, int(job.schedule))
            return now_ts + interval
        if job.schedule_type == "cron":
            next_dt = _next_cron_time(job.schedule, now_dt)
            return next_dt.timestamp()
        raise ValueError(f"Unsupported schedule type: {job.schedule_type}")

    def create_job(self, *, name: str, schedule_type: ScheduleType, schedule: str, prompt: str) -> CronJob:
        now_ts = time.time()
        zone = self._zone()

        if schedule_type == "at":
            dt = _parse_iso_datetime(schedule, zone)
            next_run_ts = dt.timestamp()
        elif schedule_type == "every":
            next_run_ts = now_ts + max(5, int(schedule))
        elif schedule_type == "cron":
            next_run_ts = _next_cron_time(schedule, datetime.fromtimestamp(now_ts, tz=zone)).timestamp()
        else:
            raise ValueError(f"Unsupported schedule type: {schedule_type}")

        return CronJob(
            id=str(uuid.uuid4()),
            name=name.strip() or "cron-job",
            schedule_type=schedule_type,
            schedule=schedule.strip(),
            prompt=prompt.strip(),
            enabled=True,
            next_run_ts=next_run_ts,
            created_at=now_ts,
            updated_at=now_ts,
        )

    def upsert_job(self, job: CronJob) -> None:
        jobs = self._load_jobs()
        replaced = False
        for idx, existing in enumerate(jobs):
            if existing.id == job.id:
                jobs[idx] = job
                replaced = True
                break
        if not replaced:
            jobs.append(job)
        self._save_jobs(jobs)

    def list_jobs(self) -> list[CronJob]:
        return self._load_jobs()

    def get_job(self, job_id: str) -> CronJob | None:
        for job in self._load_jobs():
            if job.id == job_id:
                return job
        return None

    def create_and_store_job(self, *, name: str, schedule_type: ScheduleType, schedule: str, prompt: str) -> CronJob:
        job = self.create_job(name=name, schedule_type=schedule_type, schedule=schedule, prompt=prompt)
        self.upsert_job(job)
        return job

    def delete_job(self, job_id: str) -> bool:
        jobs = self._load_jobs()
        remaining = [job for job in jobs if job.id != job_id]
        if len(remaining) == len(jobs):
            return False
        self._save_jobs(remaining)
        return True

    def query_runs(self, *, limit: int = 100) -> list[dict[str, Any]]:
        max_rows = max(1, int(limit))
        with self._file_lock:
            if not self.runs_file.exists():
                return []
            lines = [line for line in self.runs_file.read_text(encoding="utf-8").splitlines() if line.strip()]
        rows: list[dict[str, Any]] = []
        for line in reversed(lines[-max_rows:]):
            try:
                value = json.loads(line)
            except Exception:
                continue
            if isinstance(value, dict):
                rows.append(value)
        return rows

    def query_failures(self, *, limit: int = 100) -> list[dict[str, Any]]:
        max_rows = max(1, int(limit))
        with self._file_lock:
            if not self.failures_file.exists():
                return []
            lines = [line for line in self.failures_file.read_text(encoding="utf-8").splitlines() if line.strip()]
        rows: list[dict[str, Any]] = []
        for line in reversed(lines[-max_rows:]):
            try:
                value = json.loads(line)
            except Exception:
                continue
            if isinstance(value, dict):
                rows.append(value)
        return rows

    async def run_job_now(self, job_id: str) -> CronJob | None:
        async with self._async_lock:
            jobs = self._load_jobs()
            target = next((job for job in jobs if job.id == job_id), None)
            if target is None:
                return None
            await self._run_job(target, time.time())
            self.upsert_job(target)
            return target

    async def _run_job(self, job: CronJob, now_ts: float) -> None:
        session_id = f"__cron__:{job.id}"
        history = self.session_manager.load_session_for_agent(session_id)

        try:
            result = await self.agent_manager.run_once(
                message=job.prompt,
                history=history,
                session_id=session_id,
                is_first_turn=len(history) == 0,
                output_format="text",
                trigger_type="cron",
                agent_id=self.agent_id,
            )
            text = str(result.get("text", "")).strip()
            if text:
                self.session_manager.save_message(session_id, "user", job.prompt)
                self.session_manager.save_message(session_id, "assistant", text)

            job.failure_count = 0
            job.last_error = ""
            job.last_success_ts = now_ts
            job.last_run_ts = now_ts
            job.updated_at = now_ts

            next_run = self._compute_next_run(job, now_ts)
            if next_run is None:
                job.enabled = False
                job.next_run_ts = 0
            else:
                job.next_run_ts = next_run

            self._write_jsonl(
                self.runs_file,
                {
                    "timestamp_ms": int(now_ts * 1000),
                    "job_id": job.id,
                    "name": job.name,
                    "status": "ok",
                    "response_preview": text[:200],
                },
            )
        except Exception as exc:  # noqa: BLE001
            job.failure_count += 1
            job.last_error = str(exc)
            job.last_run_ts = now_ts
            job.updated_at = now_ts

            backoff = min(
                int(self.config.retry_max_seconds),
                int(self.config.retry_base_seconds) * (2 ** max(0, job.failure_count - 1)),
            )
            job.next_run_ts = now_ts + max(5, backoff)
            if job.failure_count >= int(self.config.max_failures):
                job.enabled = False

            self._write_jsonl(
                self.failures_file,
                {
                    "timestamp_ms": int(now_ts * 1000),
                    "job_id": job.id,
                    "name": job.name,
                    "status": "error",
                    "error": str(exc),
                    "failure_count": job.failure_count,
                    "next_run_ts": job.next_run_ts,
                    "disabled": not job.enabled,
                },
            )
            self._trim_failures()

    async def tick_once(self) -> None:
        async with self._async_lock:
            jobs = self._load_jobs()
            if not jobs:
                return

            now_ts = time.time()
            changed = False
            for job in jobs:
                if not job.enabled:
                    continue
                if job.next_run_ts > now_ts:
                    continue
                await self._run_job(job, now_ts)
                changed = True

            if changed:
                self._save_jobs(jobs)

    async def run(self) -> None:
        while not self._stop_event.is_set():
            await self.tick_once()
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=max(5, int(self.config.poll_interval_seconds)),
                )
            except asyncio.TimeoutError:
                continue

    def start(self) -> None:
        if self._task is not None or not self.config.enabled:
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self.run(), name="cron-scheduler")

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
