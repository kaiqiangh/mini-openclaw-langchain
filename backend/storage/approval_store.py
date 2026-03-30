"""Approval request store for high-risk tool execution."""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


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
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self._store_dir = base_dir / "storage" / "approvals"
        self._store_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, agent_id: str) -> Path:
        return self._store_dir / f"{agent_id}.jsonl"

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
        return request

    def get_request(self, agent_id: str, request_id: str) -> ApprovalRequest | None:
        path = self._path(agent_id)
        if not path.exists():
            return None
        latest_status: dict[str, str] = {}
        all_data: dict[str, dict[str, Any]] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            rid = data.get("request_id", "")
            if not rid:
                continue
            if data.get("event") == "resolution":
                latest_status[rid] = data.get("status", "pending")
                continue
            if rid not in all_data:
                all_data[rid] = data

        data = all_data.get(request_id)
        if data is None:
            return None
        status_str = latest_status.get(request_id, data.get("status", "pending"))
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
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "request_id": request_id,
                "agent_id": agent_id,
                "status": status.value,
                "resolved_at": time.time(),
                "reason": reason,
                "event": "resolution",
            }) + "\n")
        return True

    def list_pending(self, agent_id: str, limit: int = 50) -> list[ApprovalRequest]:
        path = self._path(agent_id)
        if not path.exists():
            return []
        # Two-pass: first collect all resolutions, then collect pending
        resolved: set[str] = set()
        all_creates: dict[str, dict[str, Any]] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            rid = data.get("request_id", "")
            if not rid:
                continue
            if data.get("event") == "resolution":
                resolved.add(rid)
                continue
            if data.get("status") == "pending" and rid not in all_creates:
                all_creates[rid] = data

        results: list[ApprovalRequest] = []
        now = time.time()
        for rid, data in all_creates.items():
            if rid in resolved:
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
        results.sort(key=lambda r: r.created_at, reverse=True)
        return results
