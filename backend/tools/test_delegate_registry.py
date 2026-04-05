import time
from pathlib import Path

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
