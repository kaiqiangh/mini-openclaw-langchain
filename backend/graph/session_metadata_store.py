from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from graph.session_manager import SessionManager


class SessionMetadataStore:
    def __init__(self, manager: SessionManager) -> None:
        self.manager = manager

    @staticmethod
    def _now() -> float:
        return time.time()

    def create_session(
        self,
        session_id: str,
        *,
        title: str = "New Session",
        archived: bool = False,
    ) -> dict[str, Any]:
        return self.manager.create_session(session_id, title=title, archived=archived)

    def load_existing(
        self, session_id: str, *, archived: bool = False
    ) -> dict[str, Any]:
        return self.manager.load_existing_session(session_id, archived=archived)

    def load(self, session_id: str, *, archived: bool = False) -> dict[str, Any]:
        return self.manager.load_session(session_id, archived=archived)

    def save(
        self, session_id: str, payload: dict[str, Any], *, archived: bool = False
    ) -> None:
        self.manager.save_session(session_id, payload, archived=archived)

    def list_sessions(self, *, scope: str = "active") -> list[dict[str, Any]]:
        return self.manager.list_sessions(scope=scope)

    def rename_session(self, session_id: str, title: str) -> dict[str, Any]:
        return self.manager.rename_session(session_id, title)

    def update_title(self, session_id: str, title: str) -> None:
        self.manager.update_title(session_id, title)

    def delete_session(self, session_id: str, *, archived: bool = False) -> bool:
        return self.manager.delete_session(session_id, archived=archived)

    def archive_session(self, session_id: str) -> bool:
        return self.manager.archive_session(session_id)

    def restore_session(self, session_id: str) -> bool:
        return self.manager.restore_session(session_id)

    def get_compressed_context(
        self, session_id: str, *, archived: bool = False
    ) -> str:
        session = self.load(session_id, archived=archived)
        return str(session.get("compressed_context", "")).strip()

    def update_compressed_context(
        self,
        session_id: str,
        summary: str,
        *,
        archived: bool = False,
    ) -> None:
        session = self.load(session_id, archived=archived)
        prior = str(session.get("compressed_context", "")).strip()
        normalized = summary.strip()
        if prior and normalized:
            session["compressed_context"] = f"{prior}\n---\n{normalized}"
        else:
            session["compressed_context"] = normalized or prior
        self.save(session_id, session, archived=archived)

    def replace_compressed_context(
        self,
        session_id: str,
        value: str,
        *,
        archived: bool = False,
    ) -> None:
        session = self.load(session_id, archived=archived)
        session["compressed_context"] = value.strip()
        self.save(session_id, session, archived=archived)

    def get_live_response(
        self, session_id: str, *, archived: bool = False
    ) -> dict[str, Any] | None:
        session = self.load(session_id, archived=archived)
        live = session.get("live_response")
        return dict(live) if isinstance(live, dict) else None

    def set_live_response(
        self,
        session_id: str,
        *,
        run_id: str,
        content: str,
        tool_calls: list[dict[str, Any]] | None = None,
        skill_uses: list[str] | None = None,
        selected_skills: list[str] | None = None,
        archived: bool = False,
    ) -> None:
        session = self.load(session_id, archived=archived)
        existing = session.get("live_response")
        existing_ts = 0
        if isinstance(existing, dict):
            try:
                existing_ts = int(existing.get("timestamp_ms", 0))
            except Exception:
                existing_ts = 0
        payload: dict[str, Any] = {
            "run_id": run_id,
            "content": content,
            "timestamp_ms": existing_ts or int(self._now() * 1000),
            "updated_at": self._now(),
        }
        if tool_calls:
            payload["tool_calls"] = tool_calls
        if skill_uses:
            payload["skill_uses"] = list(dict.fromkeys(skill_uses))
        if selected_skills:
            payload["selected_skills"] = list(dict.fromkeys(selected_skills))
        session["live_response"] = payload
        self.save(session_id, session, archived=archived)

    def clear_live_response(
        self,
        session_id: str,
        *,
        run_id: str | None = None,
        archived: bool = False,
    ) -> None:
        session = self.load(session_id, archived=archived)
        live = session.get("live_response")
        if not isinstance(live, dict):
            return
        if run_id and str(live.get("run_id", "")).strip() != run_id.strip():
            return
        session.pop("live_response", None)
        self.save(session_id, session, archived=archived)

    def get_legacy_messages(
        self, session_id: str, *, archived: bool = False
    ) -> list[dict[str, Any]]:
        session = self.load(session_id, archived=archived)
        messages = session.get("messages", [])
        return [dict(item) for item in messages if isinstance(item, dict)]

    def mark_checkpoint_migrated(
        self,
        session_id: str,
        *,
        imported_message_count: int,
        archived: bool = False,
    ) -> None:
        session = self.load(session_id, archived=archived)
        session["checkpoint_migrated_at"] = self._now()
        session["checkpoint_imported_message_count"] = max(0, int(imported_message_count))
        session["messages"] = []
        self.save(session_id, session, archived=archived)

    def is_checkpoint_migrated(
        self, session_id: str, *, archived: bool = False
    ) -> bool:
        session = self.load(session_id, archived=archived)
        return bool(session.get("checkpoint_migrated_at"))

    def write_archive_snapshot(
        self,
        session_id: str,
        payload: list[dict[str, Any]],
    ) -> Path:
        archive_path = self.manager.archive_dir / f"{session_id}_{int(self._now())}.json"
        self.manager._write_json_file(archive_path, payload)  # noqa: SLF001
        return archive_path
