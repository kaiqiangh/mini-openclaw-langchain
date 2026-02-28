from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from utils.redaction import redact_json_line


class AuditStore:
    """Structured JSONL audit store with stable record categories."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.audit_dir = base_dir / "storage" / "audit"
        self.audit_dir.mkdir(parents=True, exist_ok=True)
        self.runs_file = self.audit_dir / "runs.jsonl"
        self.steps_file = self.audit_dir / "steps.jsonl"
        self.tool_calls_file = self.audit_dir / "tool_calls.jsonl"
        self.message_links_file = self.audit_dir / "message_links.jsonl"
        self._lock = threading.Lock()

    def _append(self, file_path: Path, payload: dict[str, Any]) -> None:
        payload.setdefault("timestamp_ms", int(time.time() * 1000))
        line = redact_json_line(payload)
        with self._lock:
            with file_path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")

    def append_run(
        self,
        *,
        run_id: str,
        session_id: str,
        trigger_type: str,
        status: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self._append(
            self.runs_file,
            {
                "schema": "audit.run.v1",
                "run_id": run_id,
                "session_id": session_id,
                "trigger_type": trigger_type,
                "status": status,
                "details": details or {},
            },
        )

    def append_step(
        self,
        *,
        run_id: str,
        session_id: str,
        trigger_type: str,
        event: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self._append(
            self.steps_file,
            {
                "schema": "audit.step.v1",
                "run_id": run_id,
                "session_id": session_id,
                "trigger_type": trigger_type,
                "event": event,
                "details": details or {},
            },
        )

    def append_tool_call(
        self,
        *,
        run_id: str | None,
        session_id: str | None,
        trigger_type: str,
        tool_name: str,
        status: str,
        duration_ms: int,
        details: dict[str, Any] | None = None,
    ) -> None:
        self._append(
            self.tool_calls_file,
            {
                "schema": "audit.tool_call.v1",
                "run_id": run_id or "",
                "session_id": session_id or "",
                "trigger_type": trigger_type,
                "tool_name": tool_name,
                "status": status,
                "duration_ms": duration_ms,
                "details": details or {},
            },
        )

    def append_message_link(
        self,
        *,
        run_id: str | None,
        session_id: str,
        role: str,
        segment_index: int,
        content: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self._append(
            self.message_links_file,
            {
                "schema": "audit.message_link.v1",
                "run_id": run_id or "",
                "session_id": session_id,
                "role": role,
                "segment_index": segment_index,
                "content_preview": content[:300],
                "details": details or {},
            },
        )

    def ensure_schema_descriptor(self) -> None:
        descriptor = {
            "version": 1,
            "files": {
                "runs": "runs.jsonl",
                "steps": "steps.jsonl",
                "tool_calls": "tool_calls.jsonl",
                "message_links": "message_links.jsonl",
            },
            "schemas": {
                "runs": "audit.run.v1",
                "steps": "audit.step.v1",
                "tool_calls": "audit.tool_call.v1",
                "message_links": "audit.message_link.v1",
            },
        }
        schema_path = self.audit_dir / "SCHEMA.json"
        if not schema_path.exists():
            schema_path.write_text(
                json.dumps(descriptor, ensure_ascii=True, indent=2) + "\n",
                encoding="utf-8",
            )
