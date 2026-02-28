from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import time
from typing import Any, Literal

from fastapi import APIRouter, Query
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
    _BASE_DIR = base_dir
    _AGENT_MANAGER = agent_manager
    _DEFAULT_HEARTBEAT_SCHEDULER = default_heartbeat_scheduler
    _DEFAULT_CRON_SCHEDULER = default_cron_scheduler


def _require_manager() -> AgentManager:
    if _AGENT_MANAGER is None:
        raise ApiError(status_code=500, code="not_initialized", message="Scheduler API dependencies are not initialized")
    return _AGENT_MANAGER


def _runtime(agent_id: str):
    manager = _require_manager()
    try:
        runtime = manager.get_runtime(agent_id)
    except ValueError as exc:
        raise ApiError(status_code=400, code="invalid_request", message=str(exc)) from exc
    if not runtime.runtime_config.scheduler.api_enabled:
        raise ApiError(status_code=403, code="scheduler_api_disabled", message="Scheduler API is disabled")
    return manager, runtime


def _cron_scheduler(agent_id: str) -> CronScheduler:
    manager, runtime = _runtime(agent_id)
    if agent_id == "default" and _DEFAULT_CRON_SCHEDULER is not None:
        _DEFAULT_CRON_SCHEDULER.config = runtime.runtime_config.cron
        return _DEFAULT_CRON_SCHEDULER
    return CronScheduler(
        base_dir=runtime.root_dir,
        config=runtime.runtime_config.cron,
        agent_manager=manager,
        session_manager=runtime.session_manager,
        agent_id=runtime.agent_id,
    )


def _heartbeat_scheduler(agent_id: str) -> HeartbeatScheduler:
    manager, runtime = _runtime(agent_id)
    if agent_id == "default" and _DEFAULT_HEARTBEAT_SCHEDULER is not None:
        _DEFAULT_HEARTBEAT_SCHEDULER.config = runtime.runtime_config.heartbeat
        return _DEFAULT_HEARTBEAT_SCHEDULER
    return HeartbeatScheduler(
        base_dir=runtime.root_dir,
        config=runtime.runtime_config.heartbeat,
        agent_manager=manager,
        session_manager=runtime.session_manager,
        agent_id=runtime.agent_id,
    )


def _serialize_cron_job(job: CronJob) -> dict[str, Any]:
    return asdict(job)


@router.get("/scheduler/cron/jobs")
async def list_cron_jobs(
    agent_id: str = Query(default="default", min_length=1, max_length=64),
) -> dict[str, Any]:
    scheduler = _cron_scheduler(agent_id)
    jobs = [_serialize_cron_job(job) for job in scheduler.list_jobs()]
    return {"data": {"agent_id": agent_id, "jobs": jobs}}


@router.post("/scheduler/cron/jobs")
async def create_cron_job(
    request: CronJobCreateRequest,
    agent_id: str = Query(default="default", min_length=1, max_length=64),
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
        raise ApiError(status_code=400, code="invalid_request", message=str(exc)) from exc
    if request.enabled is False:
        job.enabled = False
        job.next_run_ts = 0
        scheduler.upsert_job(job)
    return {"data": {"agent_id": agent_id, "job": _serialize_cron_job(job)}}


@router.put("/scheduler/cron/jobs/{job_id}")
async def update_cron_job(
    job_id: str,
    request: CronJobUpdateRequest,
    agent_id: str = Query(default="default", min_length=1, max_length=64),
) -> dict[str, Any]:
    scheduler = _cron_scheduler(agent_id)
    current = scheduler.get_job(job_id)
    if current is None:
        raise ApiError(status_code=404, code="not_found", message="Cron job not found")

    next_name = request.name if request.name is not None else current.name
    next_type = request.schedule_type if request.schedule_type is not None else current.schedule_type
    next_schedule = request.schedule if request.schedule is not None else current.schedule
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
            raise ApiError(status_code=400, code="invalid_request", message=str(exc)) from exc
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


@router.delete("/scheduler/cron/jobs/{job_id}")
async def delete_cron_job(
    job_id: str,
    agent_id: str = Query(default="default", min_length=1, max_length=64),
) -> dict[str, Any]:
    scheduler = _cron_scheduler(agent_id)
    deleted = scheduler.delete_job(job_id)
    if not deleted:
        raise ApiError(status_code=404, code="not_found", message="Cron job not found")
    return {"data": {"agent_id": agent_id, "deleted": True, "job_id": job_id}}


@router.post("/scheduler/cron/jobs/{job_id}/run")
async def run_cron_job(
    job_id: str,
    agent_id: str = Query(default="default", min_length=1, max_length=64),
) -> dict[str, Any]:
    scheduler = _cron_scheduler(agent_id)
    job = await scheduler.run_job_now(job_id)
    if job is None:
        raise ApiError(status_code=404, code="not_found", message="Cron job not found")
    return {"data": {"agent_id": agent_id, "job": _serialize_cron_job(job)}}


@router.get("/scheduler/cron/runs")
async def list_cron_runs(
    agent_id: str = Query(default="default", min_length=1, max_length=64),
    limit: int | None = Query(default=None, ge=1, le=5000),
) -> dict[str, Any]:
    _, runtime = _runtime(agent_id)
    scheduler = _cron_scheduler(agent_id)
    rows = scheduler.query_runs(limit=limit or runtime.runtime_config.scheduler.runs_query_default_limit)
    return {"data": {"agent_id": agent_id, "runs": rows}}


@router.get("/scheduler/cron/failures")
async def list_cron_failures(
    agent_id: str = Query(default="default", min_length=1, max_length=64),
    limit: int | None = Query(default=None, ge=1, le=5000),
) -> dict[str, Any]:
    _, runtime = _runtime(agent_id)
    scheduler = _cron_scheduler(agent_id)
    rows = scheduler.query_failures(limit=limit or runtime.runtime_config.scheduler.runs_query_default_limit)
    return {"data": {"agent_id": agent_id, "failures": rows}}


@router.get("/scheduler/heartbeat")
async def get_heartbeat_config(
    agent_id: str = Query(default="default", min_length=1, max_length=64),
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


@router.put("/scheduler/heartbeat")
async def update_heartbeat_config(
    request: HeartbeatUpdateRequest,
    agent_id: str = Query(default="default", min_length=1, max_length=64),
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
    if agent_id == "default" and _DEFAULT_HEARTBEAT_SCHEDULER is not None:
        _DEFAULT_HEARTBEAT_SCHEDULER.config = refreshed.runtime_config.heartbeat

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


@router.get("/scheduler/heartbeat/runs")
async def list_heartbeat_runs(
    agent_id: str = Query(default="default", min_length=1, max_length=64),
    limit: int | None = Query(default=None, ge=1, le=5000),
) -> dict[str, Any]:
    _, runtime = _runtime(agent_id)
    scheduler = _heartbeat_scheduler(agent_id)
    rows = scheduler.query_runs(limit=limit or runtime.runtime_config.scheduler.runs_query_default_limit)
    return {"data": {"agent_id": agent_id, "runs": rows}}
