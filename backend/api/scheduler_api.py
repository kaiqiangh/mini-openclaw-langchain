from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
import time
from typing import Any, Literal

from fastapi import APIRouter, Query, Response, status
from pydantic import BaseModel, Field

from api.errors import ApiError
from config import save_runtime_config_to_path
from graph.agent import AgentManager
from scheduler.cron import CronJob, CronScheduler
from scheduler.heartbeat import HeartbeatScheduler

router = APIRouter(tags=["scheduler"])

_BASE_DIR: Path | None = None
_AGENT_MANAGER: AgentManager | None = None
_DEFAULT_HEARTBEAT_SCHEDULER: HeartbeatScheduler | None = None
_DEFAULT_CRON_SCHEDULER: CronScheduler | None = None
_HEARTBEAT_SCHEDULERS: dict[str, HeartbeatScheduler] = {}
_CRON_SCHEDULERS: dict[str, CronScheduler] = {}


def get_cron_scheduler(agent_id: str) -> CronScheduler | None:
    """Return existing CronScheduler for agent, or None."""
    return _CRON_SCHEDULERS.get(agent_id)
_WINDOW_TO_MS = {
    "1h": 60 * 60 * 1000,
    "4h": 4 * 60 * 60 * 1000,
    "12h": 12 * 60 * 60 * 1000,
    "24h": 24 * 60 * 60 * 1000,
    "7d": 7 * 24 * 60 * 60 * 1000,
    "30d": 30 * 24 * 60 * 60 * 1000,
}
_BUCKET_TO_MS = {
    "1m": 60 * 1000,
    "5m": 5 * 60 * 1000,
    "15m": 15 * 60 * 1000,
    "1h": 60 * 60 * 1000,
}


class CronJobCreateRequest(BaseModel):
    name: str = Field(default="", max_length=120)
    schedule_type: Literal["at", "every", "cron"]
    schedule: str = Field(min_length=1, max_length=120)
    prompt: str = Field(min_length=1, max_length=8000)
    enabled: bool = True


class CronJobUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    schedule_type: Literal["at", "every", "cron"] | None = None
    schedule: str | None = Field(default=None, max_length=120)
    prompt: str | None = Field(default=None, max_length=8000)
    enabled: bool | None = None


class HeartbeatUpdateRequest(BaseModel):
    enabled: bool | None = None
    interval_seconds: int | None = Field(default=None, ge=30, le=86400)
    timezone: str | None = Field(default=None, max_length=64)
    active_start_hour: int | None = Field(default=None, ge=0, le=23)
    active_end_hour: int | None = Field(default=None, ge=0, le=23)
    session_id: str | None = Field(default=None, max_length=128)


def set_dependencies(
    base_dir: Path,
    agent_manager: AgentManager,
    *,
    default_heartbeat_scheduler: HeartbeatScheduler | None = None,
    default_cron_scheduler: CronScheduler | None = None,
) -> None:
    global _BASE_DIR, _AGENT_MANAGER, _DEFAULT_HEARTBEAT_SCHEDULER, _DEFAULT_CRON_SCHEDULER
    global _HEARTBEAT_SCHEDULERS, _CRON_SCHEDULERS
    _BASE_DIR = base_dir
    _AGENT_MANAGER = agent_manager
    _DEFAULT_HEARTBEAT_SCHEDULER = default_heartbeat_scheduler
    _DEFAULT_CRON_SCHEDULER = default_cron_scheduler
    _HEARTBEAT_SCHEDULERS = {}
    _CRON_SCHEDULERS = {}
    if default_heartbeat_scheduler is not None:
        _HEARTBEAT_SCHEDULERS["default"] = default_heartbeat_scheduler
    if default_cron_scheduler is not None:
        _CRON_SCHEDULERS["default"] = default_cron_scheduler


def _require_manager() -> AgentManager:
    if _AGENT_MANAGER is None:
        raise ApiError(
            status_code=500,
            code="not_initialized",
            message="Scheduler API dependencies are not initialized",
        )
    return _AGENT_MANAGER


def _runtime(agent_id: str, *, require_api_enabled: bool = True):
    manager = _require_manager()
    try:
        runtime = manager.get_runtime(agent_id)
    except ValueError as exc:
        raise ApiError(
            status_code=400, code="invalid_request", message=str(exc)
        ) from exc
    if require_api_enabled and not runtime.runtime_config.scheduler.api_enabled:
        raise ApiError(
            status_code=403,
            code="scheduler_api_disabled",
            message="Scheduler API is disabled",
        )
    return manager, runtime


def _sync_heartbeat_scheduler(
    scheduler: HeartbeatScheduler, *, manager: AgentManager, runtime: Any
) -> HeartbeatScheduler:
    scheduler.base_dir = runtime.root_dir
    scheduler.config = runtime.runtime_config.heartbeat
    scheduler.agent_manager = manager
    scheduler.session_manager = runtime.session_manager
    scheduler.agent_id = runtime.agent_id
    scheduler.audit_file = runtime.root_dir / "storage" / "heartbeat_runs.jsonl"
    scheduler.prompt_file = runtime.root_dir / "workspace" / "HEARTBEAT.md"
    return scheduler


def _sync_cron_scheduler(
    scheduler: CronScheduler, *, manager: AgentManager, runtime: Any
) -> CronScheduler:
    scheduler.base_dir = runtime.root_dir
    scheduler.config = runtime.runtime_config.cron
    scheduler.agent_manager = manager
    scheduler.session_manager = runtime.session_manager
    scheduler.agent_id = runtime.agent_id
    scheduler.jobs_file = runtime.root_dir / "storage" / "cron_jobs.json"
    scheduler.runs_file = runtime.root_dir / "storage" / "cron_runs.jsonl"
    scheduler.failures_file = runtime.root_dir / "storage" / "cron_failures.jsonl"
    return scheduler


def _heartbeat_scheduler(
    agent_id: str, *, require_api_enabled: bool = True
) -> HeartbeatScheduler:
    manager, runtime = _runtime(agent_id, require_api_enabled=require_api_enabled)
    scheduler = _HEARTBEAT_SCHEDULERS.get(runtime.agent_id)
    if scheduler is None:
        if runtime.agent_id == "default" and _DEFAULT_HEARTBEAT_SCHEDULER is not None:
            scheduler = _DEFAULT_HEARTBEAT_SCHEDULER
        else:
            scheduler = HeartbeatScheduler(
                base_dir=runtime.root_dir,
                config=runtime.runtime_config.heartbeat,
                agent_manager=manager,
                session_manager=runtime.session_manager,
                agent_id=runtime.agent_id,
            )
        _HEARTBEAT_SCHEDULERS[runtime.agent_id] = scheduler
    return _sync_heartbeat_scheduler(scheduler, manager=manager, runtime=runtime)


def _cron_scheduler(
    agent_id: str, *, require_api_enabled: bool = True
) -> CronScheduler:
    manager, runtime = _runtime(agent_id, require_api_enabled=require_api_enabled)
    scheduler = _CRON_SCHEDULERS.get(runtime.agent_id)
    if scheduler is None:
        if runtime.agent_id == "default" and _DEFAULT_CRON_SCHEDULER is not None:
            scheduler = _DEFAULT_CRON_SCHEDULER
        else:
            scheduler = CronScheduler(
                base_dir=runtime.root_dir,
                config=runtime.runtime_config.cron,
                agent_manager=manager,
                session_manager=runtime.session_manager,
                agent_id=runtime.agent_id,
            )
        _CRON_SCHEDULERS[runtime.agent_id] = scheduler
    return _sync_cron_scheduler(scheduler, manager=manager, runtime=runtime)


def start_agent_schedulers(agent_id: str) -> None:
    heartbeat = _heartbeat_scheduler(agent_id, require_api_enabled=False)
    cron = _cron_scheduler(agent_id, require_api_enabled=False)
    heartbeat.start()
    cron.start()


async def stop_agent_schedulers(agent_id: str) -> None:
    heartbeat = _HEARTBEAT_SCHEDULERS.pop(agent_id, None)
    cron = _CRON_SCHEDULERS.pop(agent_id, None)
    if heartbeat is not None:
        await heartbeat.stop()
    if cron is not None:
        await cron.stop()
    if agent_id == "default":
        if _DEFAULT_HEARTBEAT_SCHEDULER is not None:
            _HEARTBEAT_SCHEDULERS["default"] = _DEFAULT_HEARTBEAT_SCHEDULER
        if _DEFAULT_CRON_SCHEDULER is not None:
            _CRON_SCHEDULERS["default"] = _DEFAULT_CRON_SCHEDULER


async def stop_all_schedulers() -> None:
    heartbeat_items = list(_HEARTBEAT_SCHEDULERS.items())
    cron_items = list(_CRON_SCHEDULERS.items())
    _HEARTBEAT_SCHEDULERS.clear()
    _CRON_SCHEDULERS.clear()
    for _, scheduler in heartbeat_items:
        await scheduler.stop()
    for _, scheduler in cron_items:
        await scheduler.stop()


def _serialize_cron_job(job: CronJob) -> dict[str, Any]:
    return asdict(job)


def _to_int(value: Any) -> int | None:
    try:
        parsed = int(float(value))
    except Exception:
        return None
    if parsed < 0:
        return None
    return parsed


def _percentile(values: list[int], percentile: int) -> int | None:
    if not values:
        return None
    sorted_values = sorted(values)
    index = max(
        0,
        min(
            len(sorted_values) - 1,
            int(round((percentile / 100) * (len(sorted_values) - 1))),
        ),
    )
    return sorted_values[index]


def _numeric_stats(samples: list[int]) -> dict[str, Any]:
    if not samples:
        return {
            "count": 0,
            "avg_ms": None,
            "min_ms": None,
            "max_ms": None,
            "p50_ms": None,
            "p90_ms": None,
            "p99_ms": None,
        }
    return {
        "count": len(samples),
        "avg_ms": int(sum(samples) / max(1, len(samples))),
        "min_ms": min(samples),
        "max_ms": max(samples),
        "p50_ms": _percentile(samples, 50),
        "p90_ms": _percentile(samples, 90),
        "p99_ms": _percentile(samples, 99),
    }


def _row_timestamp_ms(row: dict[str, Any]) -> int | None:
    for key in ("finished_at_ms", "timestamp_ms", "started_at_ms"):
        value = _to_int(row.get(key))
        if value is not None:
            return value
    return None


def _build_observability_rows(
    *,
    cron_runs: list[dict[str, Any]],
    cron_failures: list[dict[str, Any]],
    heartbeat_runs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in cron_runs:
        ts = _row_timestamp_ms(row)
        if ts is None:
            continue
        rows.append(
            {
                "source": "cron",
                "status": str(row.get("status", "ok")),
                "timestamp_ms": ts,
                "duration_ms": _to_int(row.get("duration_ms")),
                "schedule_lag_ms": _to_int(row.get("schedule_lag_ms")),
            }
        )
    for row in cron_failures:
        ts = _row_timestamp_ms(row)
        if ts is None:
            continue
        rows.append(
            {
                "source": "cron",
                "status": str(row.get("status", "error")),
                "timestamp_ms": ts,
                "duration_ms": _to_int(row.get("duration_ms")),
                "schedule_lag_ms": _to_int(row.get("schedule_lag_ms")),
            }
        )
    for row in heartbeat_runs:
        ts = _row_timestamp_ms(row)
        if ts is None:
            continue
        rows.append(
            {
                "source": "heartbeat",
                "status": str(row.get("status", "ok")),
                "timestamp_ms": ts,
                "duration_ms": _to_int(row.get("duration_ms")),
                "schedule_lag_ms": _to_int(row.get("schedule_lag_ms")),
            }
        )
    return rows


@router.get("/agents/{agent_id}/scheduler/cron/jobs")
async def list_cron_jobs(
    agent_id: str,
) -> dict[str, Any]:
    scheduler = _cron_scheduler(agent_id)
    jobs = [_serialize_cron_job(job) for job in scheduler.list_jobs()]
    return {"data": {"agent_id": agent_id, "jobs": jobs}}


@router.post(
    "/agents/{agent_id}/scheduler/cron/jobs", status_code=status.HTTP_201_CREATED
)
async def create_cron_job(
    agent_id: str,
    request: CronJobCreateRequest,
    response: Response,
) -> dict[str, Any]:
    scheduler = _cron_scheduler(agent_id)
    try:
        job = scheduler.create_and_store_job(
            name=request.name,
            schedule_type=request.schedule_type,
            schedule=request.schedule,
            prompt=request.prompt,
        )
    except ValueError as exc:
        raise ApiError(
            status_code=400, code="invalid_request", message=str(exc)
        ) from exc
    if request.enabled is False:
        job.enabled = False
        job.next_run_ts = 0
        scheduler.upsert_job(job)
    response.headers["Location"] = (
        f"/api/v1/agents/{agent_id}/scheduler/cron/jobs/{job.id}"
    )
    return {"data": {"agent_id": agent_id, "job": _serialize_cron_job(job)}}


@router.put("/agents/{agent_id}/scheduler/cron/jobs/{job_id}")
async def update_cron_job(
    agent_id: str,
    job_id: str,
    request: CronJobUpdateRequest,
) -> dict[str, Any]:
    scheduler = _cron_scheduler(agent_id)
    current = scheduler.get_job(job_id)
    if current is None:
        raise ApiError(status_code=404, code="not_found", message="Cron job not found")

    next_name = request.name if request.name is not None else current.name
    next_type = (
        request.schedule_type
        if request.schedule_type is not None
        else current.schedule_type
    )
    next_schedule = (
        request.schedule if request.schedule is not None else current.schedule
    )
    next_prompt = request.prompt if request.prompt is not None else current.prompt
    next_enabled = request.enabled if request.enabled is not None else current.enabled

    if next_type != current.schedule_type or next_schedule != current.schedule:
        try:
            refreshed = scheduler.create_job(
                name=next_name,
                schedule_type=next_type,
                schedule=next_schedule,
                prompt=next_prompt,
            )
        except ValueError as exc:
            raise ApiError(
                status_code=400, code="invalid_request", message=str(exc)
            ) from exc
        current.schedule_type = refreshed.schedule_type
        current.schedule = refreshed.schedule
        current.next_run_ts = refreshed.next_run_ts

    current.name = next_name.strip() or current.name
    current.prompt = next_prompt.strip() or current.prompt
    current.enabled = bool(next_enabled)
    current.updated_at = time.time()
    if not current.enabled:
        current.next_run_ts = 0
    elif current.next_run_ts <= 0:
        try:
            refreshed = scheduler.create_job(
                name=current.name,
                schedule_type=current.schedule_type,
                schedule=current.schedule,
                prompt=current.prompt,
            )
            current.next_run_ts = refreshed.next_run_ts
        except ValueError:
            pass
    scheduler.upsert_job(current)
    return {"data": {"agent_id": agent_id, "job": _serialize_cron_job(current)}}


@router.delete(
    "/agents/{agent_id}/scheduler/cron/jobs/{job_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_cron_job(
    agent_id: str,
    job_id: str,
) -> Response:
    scheduler = _cron_scheduler(agent_id)
    deleted = scheduler.delete_job(job_id)
    if not deleted:
        raise ApiError(status_code=404, code="not_found", message="Cron job not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/agents/{agent_id}/scheduler/cron/jobs/{job_id}/run")
async def run_cron_job(
    agent_id: str,
    job_id: str,
) -> dict[str, Any]:
    scheduler = _cron_scheduler(agent_id)
    job = await scheduler.run_job_now(job_id)
    if job is None:
        raise ApiError(status_code=404, code="not_found", message="Cron job not found")
    return {"data": {"agent_id": agent_id, "job": _serialize_cron_job(job)}}


@router.get("/agents/{agent_id}/scheduler/cron/runs")
async def list_cron_runs(
    agent_id: str,
    limit: int | None = Query(default=None, ge=1, le=5000),
) -> dict[str, Any]:
    _, runtime = _runtime(agent_id)
    scheduler = _cron_scheduler(agent_id)
    rows = scheduler.query_runs(
        limit=limit or runtime.runtime_config.scheduler.runs_query_default_limit
    )
    return {"data": {"agent_id": agent_id, "runs": rows}}


@router.get("/agents/{agent_id}/scheduler/cron/failures")
async def list_cron_failures(
    agent_id: str,
    limit: int | None = Query(default=None, ge=1, le=5000),
) -> dict[str, Any]:
    _, runtime = _runtime(agent_id)
    scheduler = _cron_scheduler(agent_id)
    rows = scheduler.query_failures(
        limit=limit or runtime.runtime_config.scheduler.runs_query_default_limit
    )
    return {"data": {"agent_id": agent_id, "failures": rows}}


@router.get("/agents/{agent_id}/scheduler/heartbeat")
async def get_heartbeat_config(
    agent_id: str,
) -> dict[str, Any]:
    scheduler = _heartbeat_scheduler(agent_id)
    return {
        "data": {
            "agent_id": agent_id,
            "config": {
                "enabled": scheduler.config.enabled,
                "interval_seconds": scheduler.config.interval_seconds,
                "timezone": scheduler.config.timezone,
                "active_start_hour": scheduler.config.active_start_hour,
                "active_end_hour": scheduler.config.active_end_hour,
                "session_id": scheduler.config.session_id,
            },
        }
    }


@router.put("/agents/{agent_id}/scheduler/heartbeat")
async def update_heartbeat_config(
    agent_id: str,
    request: HeartbeatUpdateRequest,
) -> dict[str, Any]:
    manager, runtime = _runtime(agent_id)
    config_path = manager.get_agent_config_path(agent_id)
    runtime_config = runtime.runtime_config
    heartbeat = runtime_config.heartbeat

    if request.enabled is not None:
        heartbeat.enabled = request.enabled
    if request.interval_seconds is not None:
        heartbeat.interval_seconds = max(30, int(request.interval_seconds))
    if request.timezone is not None:
        heartbeat.timezone = request.timezone.strip() or heartbeat.timezone
    if request.active_start_hour is not None:
        heartbeat.active_start_hour = int(request.active_start_hour) % 24
    if request.active_end_hour is not None:
        heartbeat.active_end_hour = int(request.active_end_hour) % 24
    if request.session_id is not None:
        heartbeat.session_id = request.session_id.strip() or heartbeat.session_id

    save_runtime_config_to_path(config_path, runtime_config)

    refreshed = manager.get_runtime(agent_id)
    heartbeat_scheduler = _heartbeat_scheduler(
        agent_id, require_api_enabled=False
    )
    heartbeat_scheduler.config = refreshed.runtime_config.heartbeat
    if refreshed.runtime_config.heartbeat.enabled:
        heartbeat_scheduler.start()
    else:
        await heartbeat_scheduler.stop()

    return {
        "data": {
            "agent_id": refreshed.agent_id,
            "config": {
                "enabled": refreshed.runtime_config.heartbeat.enabled,
                "interval_seconds": refreshed.runtime_config.heartbeat.interval_seconds,
                "timezone": refreshed.runtime_config.heartbeat.timezone,
                "active_start_hour": refreshed.runtime_config.heartbeat.active_start_hour,
                "active_end_hour": refreshed.runtime_config.heartbeat.active_end_hour,
                "session_id": refreshed.runtime_config.heartbeat.session_id,
            },
        }
    }


@router.get("/agents/{agent_id}/scheduler/heartbeat/runs")
async def list_heartbeat_runs(
    agent_id: str,
    limit: int | None = Query(default=None, ge=1, le=5000),
) -> dict[str, Any]:
    _, runtime = _runtime(agent_id)
    scheduler = _heartbeat_scheduler(agent_id)
    rows = scheduler.query_runs(
        limit=limit or runtime.runtime_config.scheduler.runs_query_default_limit
    )
    return {"data": {"agent_id": agent_id, "runs": rows}}


@router.get("/agents/{agent_id}/scheduler/metrics")
async def get_scheduler_metrics(
    agent_id: str,
    window: Literal["1h", "4h", "12h", "24h", "7d", "30d"] = Query(default="24h"),
) -> dict[str, Any]:
    _runtime(agent_id)
    now_ms = int(time.time() * 1000)
    since_ms = now_ms - _WINDOW_TO_MS[window]

    cron_scheduler = _cron_scheduler(agent_id)
    heartbeat_scheduler = _heartbeat_scheduler(agent_id)
    scan_limit = 100_000
    cron_runs = cron_scheduler.query_runs(limit=scan_limit, since_ms=since_ms)
    cron_failures = cron_scheduler.query_failures(limit=scan_limit, since_ms=since_ms)
    heartbeat_runs = heartbeat_scheduler.query_runs(limit=scan_limit, since_ms=since_ms)
    rows = _build_observability_rows(
        cron_runs=cron_runs,
        cron_failures=cron_failures,
        heartbeat_runs=heartbeat_runs,
    )

    duration_samples = [
        value
        for value in (_to_int(item.get("duration_ms")) for item in rows)
        if value is not None
    ]
    lag_samples = [
        value
        for value in (_to_int(item.get("schedule_lag_ms")) for item in rows)
        if value is not None
    ]

    status_breakdown: dict[str, int] = {}
    for row in rows:
        key = str(row.get("status", "unknown"))
        status_breakdown[key] = status_breakdown.get(key, 0) + 1

    cron_error_count = len(cron_failures)
    cron_success_count = len(cron_runs)
    cron_total = cron_success_count + cron_error_count
    heartbeat_total = len(heartbeat_runs)
    heartbeat_ok = len(
        [row for row in heartbeat_runs if str(row.get("status", "ok")) == "ok"]
    )
    heartbeat_error = len(
        [row for row in heartbeat_runs if str(row.get("status", "")) == "error"]
    )
    heartbeat_skipped = max(0, heartbeat_total - heartbeat_ok - heartbeat_error)

    return {
        "data": {
            "agent_id": agent_id,
            "window": window,
            "since_ms": since_ms,
            "generated_at_ms": now_ms,
            "totals": {
                "events": len(rows),
                "cron_events": cron_total,
                "heartbeat_events": heartbeat_total,
            },
            "cron": {
                "runs": cron_total,
                "ok": cron_success_count,
                "error": cron_error_count,
                "success_rate": (
                    round((cron_success_count / max(1, cron_total)) * 100, 2)
                    if cron_total
                    else None
                ),
            },
            "heartbeat": {
                "runs": heartbeat_total,
                "ok": heartbeat_ok,
                "error": heartbeat_error,
                "skipped": heartbeat_skipped,
            },
            "duration": _numeric_stats(duration_samples),
            "latency": _numeric_stats(lag_samples),
            "status_breakdown": status_breakdown,
        }
    }


@router.get("/agents/{agent_id}/scheduler/metrics/timeseries")
async def get_scheduler_metrics_timeseries(
    agent_id: str,
    window: Literal["1h", "4h", "12h", "24h", "7d", "30d"] = Query(default="24h"),
    bucket: Literal["1m", "5m", "15m", "1h"] = Query(default="5m"),
) -> dict[str, Any]:
    _runtime(agent_id)
    now_ms = int(time.time() * 1000)
    since_ms = now_ms - _WINDOW_TO_MS[window]
    bucket_ms = _BUCKET_TO_MS[bucket]

    cron_scheduler = _cron_scheduler(agent_id)
    heartbeat_scheduler = _heartbeat_scheduler(agent_id)
    scan_limit = 100_000
    rows = _build_observability_rows(
        cron_runs=cron_scheduler.query_runs(limit=scan_limit, since_ms=since_ms),
        cron_failures=cron_scheduler.query_failures(limit=scan_limit, since_ms=since_ms),
        heartbeat_runs=heartbeat_scheduler.query_runs(limit=scan_limit, since_ms=since_ms),
    )
    bucket_start_ms = since_ms - (since_ms % bucket_ms)
    bucket_end_ms = now_ms - (now_ms % bucket_ms)

    points: dict[int, dict[str, Any]] = {}
    cursor = bucket_start_ms
    while cursor <= bucket_end_ms:
        points[cursor] = {
            "ts_ms": cursor,
            "label": datetime.fromtimestamp(cursor / 1000, tz=timezone.utc).isoformat(),
            "total": 0,
            "cron_runs": 0,
            "cron_failures": 0,
            "heartbeat_runs": 0,
            "heartbeat_ok": 0,
            "heartbeat_error": 0,
            "heartbeat_skipped": 0,
            "duration_sum_ms": 0,
            "duration_count": 0,
            "latency_sum_ms": 0,
            "latency_count": 0,
        }
        cursor += bucket_ms

    for row in rows:
        ts = _to_int(row.get("timestamp_ms"))
        if ts is None or ts < since_ms or ts > now_ms:
            continue
        key = ts - (ts % bucket_ms)
        point = points.get(key)
        if point is None:
            continue
        point["total"] += 1
        source = str(row.get("source", "unknown"))
        status_value = str(row.get("status", "unknown"))
        if source == "cron":
            if status_value == "error":
                point["cron_failures"] += 1
            else:
                point["cron_runs"] += 1
        elif source == "heartbeat":
            point["heartbeat_runs"] += 1
            if status_value == "ok":
                point["heartbeat_ok"] += 1
            elif status_value == "error":
                point["heartbeat_error"] += 1
            else:
                point["heartbeat_skipped"] += 1

        duration_ms = _to_int(row.get("duration_ms"))
        if duration_ms is not None:
            point["duration_sum_ms"] += duration_ms
            point["duration_count"] += 1
        lag_ms = _to_int(row.get("schedule_lag_ms"))
        if lag_ms is not None:
            point["latency_sum_ms"] += lag_ms
            point["latency_count"] += 1

    series: list[dict[str, Any]] = []
    for key in sorted(points.keys()):
        point = points[key]
        duration_count = int(point.pop("duration_count"))
        duration_sum = int(point.pop("duration_sum_ms"))
        latency_count = int(point.pop("latency_count"))
        latency_sum = int(point.pop("latency_sum_ms"))
        point["avg_duration_ms"] = (
            int(duration_sum / max(1, duration_count)) if duration_count else None
        )
        point["avg_latency_ms"] = (
            int(latency_sum / max(1, latency_count)) if latency_count else None
        )
        series.append(point)

    return {
        "data": {
            "agent_id": agent_id,
            "window": window,
            "bucket": bucket,
            "since_ms": since_ms,
            "generated_at_ms": now_ms,
            "points": series,
        }
    }
