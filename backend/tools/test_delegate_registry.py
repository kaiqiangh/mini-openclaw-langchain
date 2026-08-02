import json
import time
from pathlib import Path

import pytest

from graph.session_manager import InvalidSessionIdError
from tools.delegate_registry import DelegateRegistry


def test_register_and_get_status(tmp_path: Path):
    registry = DelegateRegistry(base_dir=tmp_path)
    reg = registry.register(
        "alpha",
        "sess_parent",
        "Research APIs",
        "researcher",
        ["web_search"],
        [],
        30,
    )
    status = registry.get_status(reg["delegate_id"])
    assert status.status == "running"
    assert status.parent_session_id == "sess_parent"
    assert status.role == "researcher"


def test_register_encodes_colon_bearing_parent_session_path(tmp_path: Path):
    registry = DelegateRegistry(base_dir=tmp_path)
    reg = registry.register(
        "alpha", "__cron__:cron-1", "Research APIs", "researcher", ["web_search"], [], 30
    )

    assert (
        tmp_path
        / "workspaces"
        / "alpha"
        / "sessions"
        / "__cron__%3Acron-1"
        / "delegates"
        / reg["delegate_id"]
        / "config.json"
    ).exists()
    restored = DelegateRegistry(base_dir=tmp_path).get_status(reg["delegate_id"])
    assert restored is not None
    assert restored.parent_session_id == "__cron__:cron-1"


def test_register_rejects_invalid_parent_session_path(tmp_path: Path):
    registry = DelegateRegistry(base_dir=tmp_path)

    with pytest.raises(InvalidSessionIdError):
        registry.register("alpha", "../escape", "Task", "researcher", ["web_search"], [], 30)


def test_list_for_session(tmp_path: Path):
    registry = DelegateRegistry(base_dir=tmp_path)
    r1 = registry.register("alpha", "sess_1", "A", "researcher", ["web_search"], [], 30)
    r2 = registry.register("alpha", "sess_1", "B", "analyst", ["read_files"], [], 30)
    registry.register("alpha", "sess_2", "C", "researcher", ["web_search"], [], 30)

    items = registry.list_for_session("alpha", "sess_1")
    assert len(items) == 2
    ids = {i.delegate_id for i in items}
    assert r1["delegate_id"] in ids
    assert r2["delegate_id"] in ids


def test_mark_completed(tmp_path: Path):
    registry = DelegateRegistry(base_dir=tmp_path)
    reg = registry.register(
        "alpha", "sess_1", "Task", "researcher", ["web_search"], [], 30
    )
    time.sleep(0.01)
    registry.mark_completed(
        reg["delegate_id"],
        {
            "summary": "Found 3 APIs",
            "steps": 12,
            "tools_used": ["web_search"],
            "token_usage": {"prompt_tokens": 1000, "completion_tokens": 200},
        },
    )
    status = registry.get_status(reg["delegate_id"])
    assert status.status == "completed"
    assert status.result_summary == "Found 3 APIs"
    assert status.duration_ms > 0


def test_mark_failed(tmp_path: Path):
    registry = DelegateRegistry(base_dir=tmp_path)
    reg = registry.register(
        "alpha", "sess_1", "Task", "researcher", ["web_search"], [], 30
    )
    registry.mark_failed(reg["delegate_id"], "TimeoutError")
    status = registry.get_status(reg["delegate_id"])
    assert status.status == "failed"
    assert "TimeoutError" in status.error_message


def test_terminal_delegate_state_cannot_be_overwritten(tmp_path: Path):
    registry = DelegateRegistry(base_dir=tmp_path)
    reg = registry.register(
        "alpha", "sess_1", "Task", "researcher", ["web_search"], [], 30
    )

    registry.mark_timeout(reg["delegate_id"])
    registry.mark_completed(reg["delegate_id"], {"summary": "late result"})
    registry.mark_failed(reg["delegate_id"], "late failure")

    status = registry.get_status(reg["delegate_id"])
    assert status.status == "timeout"
    assert status.error_message == "Sub-agent exceeded timeout (30s)"


def test_max_per_session_enforced(tmp_path: Path):
    registry = DelegateRegistry(base_dir=tmp_path)
    registry.register("alpha", "sess_1", "T1", "r", ["w"], [], 30)
    registry.register("alpha", "sess_1", "T2", "r", ["w"], [], 30)
    # 2 running, max=2 → not allowed
    assert not registry.check_max_per_session("alpha", "sess_1", max_count=2)
    # 2 running, max=3 → allowed
    assert registry.check_max_per_session("alpha", "sess_1", max_count=3)


def test_registry_hydrates_from_disk(tmp_path: Path):
    original = DelegateRegistry(base_dir=tmp_path)
    reg = original.register(
        "alpha",
        "sess_parent",
        "Research APIs",
        "researcher",
        ["web_search"],
        ["fetch_url"],
        30,
    )
    original.mark_completed(
        reg["delegate_id"],
        {
            "summary": "Found useful docs",
            "steps": 4,
            "tools_used": ["web_search"],
            "token_usage": {"prompt_tokens": 9, "completion_tokens": 2},
        },
    )

    restored = DelegateRegistry(base_dir=tmp_path)
    status = restored.get_status(reg["delegate_id"])
    assert status is not None
    assert status.status == "completed"
    assert status.parent_session_id == "sess_parent"
    assert status.allowed_tools == ["web_search"]
    assert status.blocked_tools == ["fetch_url"]
    assert status.result_summary == "Found useful docs"
    listed = restored.list_for_session("alpha", "sess_parent")
    assert [item.delegate_id for item in listed] == [reg["delegate_id"]]


def test_registry_marks_expired_running_delegate_as_timeout_on_hydrate(tmp_path: Path):
    original = DelegateRegistry(base_dir=tmp_path)
    reg = original.register(
        "alpha",
        "sess_parent",
        "Research APIs",
        "researcher",
        ["web_search"],
        [],
        1,
    )

    config_path = (
        tmp_path
        / "workspaces"
        / "alpha"
        / "sessions"
        / "sess_parent"
        / "delegates"
        / reg["delegate_id"]
        / "config.json"
    )
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    raw["created_at"] = time.time() - 5
    config_path.write_text(
        json.dumps(raw, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    restored = DelegateRegistry(base_dir=tmp_path)
    status = restored.get_status(reg["delegate_id"])

    assert status is not None
    assert status.status == "timeout"
    assert status.error_message is not None
    assert "exceeded timeout" in status.error_message
