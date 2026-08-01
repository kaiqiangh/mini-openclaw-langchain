"""Approval request store for high-risk tool execution."""
from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from utils.async_io import iter_jsonl_reversed


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"


@dataclass
class ApprovalRequest:
    request_id: str
    agent_id: str
    session_id: str
    run_id: str
    tool_name: str
    tool_args: dict[str, Any]
    trigger_type: str
    status: ApprovalStatus
    created_at: float


class ApprovalStore:
    MAX_PENDING = 500
    MAX_RESOLVED = 500
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self._store_dir = base_dir / "storage" / "approvals"
        self._store_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _path(self, agent_id: str) -> Path:
        return self._store_dir / f"{agent_id}.jsonl"

    def compact(self, agent_id: str) -> None:
        path = self._path(agent_id)
        if not path.exists() or path.stat().st_size < 1_048_576:
            return
        latest: dict[str, dict[str, Any]] = {}
        creates: dict[str, dict[str, Any]] = {}
        for row in iter_jsonl_reversed(path):
            request_id = str(row.get("request_id", "")).strip()
            if not request_id:
                continue
            if row.get("event") == "resolution":
                latest.setdefault(request_id, row)
            else:
                creates.setdefault(request_id, row)
        pending = [
            (float(row.get("created_at", 0) or 0), request_id, row)
            for request_id, row in creates.items()
            if request_id not in latest and row.get("status") == ApprovalStatus.PENDING.value
        ]
        resolved = [
            (float(row.get("resolved_at", 0) or 0), request_id, row)
            for request_id, row in latest.items()
            if request_id in creates
        ]
        keep_ids = {
            request_id for _, request_id, _ in sorted(pending, reverse=True)[: self.MAX_PENDING]
        }
        keep_ids.update(
            request_id for _, request_id, _ in sorted(resolved, reverse=True)[: self.MAX_RESOLVED]
        )
        rows: list[dict[str, Any]] = []
        for request_id in keep_ids:
            rows.append(creates[request_id])
            if request_id in latest:
                rows.append(latest[request_id])
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
            encoding="utf-8",
        )
        tmp.replace(path)

    def create_request(
        self,
        *,
        agent_id: str,
        session_id: str,
        run_id: str,
        tool_name: str,
        tool_args: dict[str, Any],
        trigger_type: str,
        ttl_seconds: int = 300,
    ) -> ApprovalRequest:
        request_id = str(uuid.uuid4())
        now = time.time()
        request = ApprovalRequest(
            request_id=request_id,
            agent_id=agent_id,
            session_id=session_id,
            run_id=run_id,
            tool_name=tool_name,
            tool_args=tool_args,
            trigger_type=trigger_type,
            status=ApprovalStatus.PENDING,
            created_at=now,
        )
        path = self._path(agent_id)
        with self._lock:
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "request_id": request_id,
                    "agent_id": agent_id,
                    "session_id": session_id,
                    "run_id": run_id,
                    "tool_name": tool_name,
                    "tool_args": tool_args,
                    "trigger_type": trigger_type,
                    "status": ApprovalStatus.PENDING.value,
                    "created_at": now,
                    "ttl_seconds": ttl_seconds,
                }) + "\n")
            self.compact(agent_id)
        return request

    def get_request(self, agent_id: str, request_id: str) -> ApprovalRequest | None:
        path = self._path(agent_id)
        with self._lock:
            if not path.exists():
                return None
        latest_status: str | None = None
        data: dict[str, Any] | None = None
        for row in iter_jsonl_reversed(path):
            if str(row.get("request_id", "")).strip() != request_id:
                continue
            if row.get("event") == "resolution" and latest_status is None:
                latest_status = str(row.get("status", "pending"))
            elif row.get("event") != "resolution":
                data = row
                break
        if data is None:
            return None
        status_str = latest_status or str(data.get("status", "pending"))
        try:
            status = ApprovalStatus(status_str)
        except ValueError:
            status = ApprovalStatus.PENDING
        return ApprovalRequest(
            request_id=data["request_id"],
            agent_id=data["agent_id"],
            session_id=data.get("session_id", ""),
            run_id=data.get("run_id", ""),
            tool_name=data["tool_name"],
            tool_args=data.get("tool_args", {}),
            trigger_type=data.get("trigger_type", "chat"),
            status=status,
            created_at=data.get("created_at", 0),
        )

    def resolve_request(
        self,
        agent_id: str,
        request_id: str,
        status: ApprovalStatus,
        reason: str | None = None,
    ) -> bool:
        path = self._path(agent_id)
        with self._lock:
            existing = self.get_request(agent_id, request_id)
            if existing is None or existing.status != ApprovalStatus.PENDING:
                return False
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "request_id": request_id,
                    "agent_id": agent_id,
                    "status": status.value,
                    "resolved_at": time.time(),
                    "reason": reason,
                    "event": "resolution",
                }) + "\n")
            self.compact(agent_id)
            return True

    def list_pending(self, agent_id: str, limit: int = 50) -> list[ApprovalRequest]:
        path = self._path(agent_id)
        with self._lock:
            if not path.exists():
                return []
        results: list[ApprovalRequest] = []
        now = time.time()
        resolved: set[str] = set()
        seen_creates: set[str] = set()
        for data in iter_jsonl_reversed(path):
            rid = str(data.get("request_id", "")).strip()
            if not rid or rid in seen_creates:
                continue
            if data.get("event") == "resolution":
                resolved.add(rid)
                continue
            seen_creates.add(rid)
            if rid in resolved or data.get("status") != "pending":
                continue
            ttl = data.get("ttl_seconds", 300)
            if now - data.get("created_at", 0) > ttl:
                continue
            results.append(ApprovalRequest(
                request_id=data["request_id"],
                agent_id=data["agent_id"],
                session_id=data.get("session_id", ""),
                run_id=data.get("run_id", ""),
                tool_name=data["tool_name"],
                tool_args=data.get("tool_args", {}),
                trigger_type=data.get("trigger_type", "chat"),
                status=ApprovalStatus.PENDING,
                created_at=data.get("created_at", 0),
            ))
            if len(results) >= limit:
                break
        return results
