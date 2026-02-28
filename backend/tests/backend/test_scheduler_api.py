from __future__ import annotations

import asyncio
from pathlib import Path


def test_scheduler_cron_lifecycle(client):
    created = client.post(
        "/api/scheduler/cron/jobs",
        json={
            "name": "health-check",
            "schedule_type": "every",
            "schedule": "60",
            "prompt": "ping",
            "enabled": True,
        },
    )
    assert created.status_code == 200
    job_id = created.json()["data"]["job"]["id"]

    listed = client.get("/api/scheduler/cron/jobs")
    assert listed.status_code == 200
    assert any(row["id"] == job_id for row in listed.json()["data"]["jobs"])

    updated = client.put(
        f"/api/scheduler/cron/jobs/{job_id}",
        json={"enabled": False, "name": "health-check-2"},
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["job"]["enabled"] is False
    assert updated.json()["data"]["job"]["name"] == "health-check-2"

    run_now = client.post(f"/api/scheduler/cron/jobs/{job_id}/run")
    assert run_now.status_code == 200

    runs = client.get("/api/scheduler/cron/runs")
    assert runs.status_code == 200
    assert any(row.get("job_id") == job_id for row in runs.json()["data"]["runs"])

    failures = client.get("/api/scheduler/cron/failures")
    assert failures.status_code == 200
    assert isinstance(failures.json()["data"]["failures"], list)

    deleted = client.delete(f"/api/scheduler/cron/jobs/{job_id}")
    assert deleted.status_code == 200
    assert deleted.json()["data"]["deleted"] is True


def test_heartbeat_comment_only_prompt_is_skipped(client, api_app):
    base_dir = Path(api_app["base_dir"])
    prompt_path = base_dir / "workspace" / "HEARTBEAT.md"
    prompt_path.write_text("# comment only\n\n   # still comment\n", encoding="utf-8")

    heartbeat_scheduler = api_app["heartbeat_scheduler"]
    asyncio.run(heartbeat_scheduler._tick_once())

    rows = client.get("/api/scheduler/heartbeat/runs")
    assert rows.status_code == 200
    runs = rows.json()["data"]["runs"]
    assert runs
    assert runs[0]["status"] == "skipped_no_prompt"


def test_heartbeat_config_update_roundtrip(client):
    get_before = client.get("/api/scheduler/heartbeat")
    assert get_before.status_code == 200

    updated = client.put(
        "/api/scheduler/heartbeat",
        json={
            "enabled": True,
            "interval_seconds": 120,
            "timezone": "UTC",
            "active_start_hour": 0,
            "active_end_hour": 23,
            "session_id": "__heartbeat_test__",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["config"]["enabled"] is True
    assert updated.json()["data"]["config"]["interval_seconds"] == 120
    assert updated.json()["data"]["config"]["session_id"] == "__heartbeat_test__"
