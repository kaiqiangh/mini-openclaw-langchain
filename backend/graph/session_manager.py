from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any


class LegacySessionStateError(RuntimeError):
    pass


class SessionManager:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self._lock = asyncio.Lock()
        self.sessions_dir = base_dir / "sessions"
        self.archive_dir = self.sessions_dir / "archive"
        self.archived_sessions_dir = self.sessions_dir / "archived_sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self.archived_sessions_dir.mkdir(parents=True, exist_ok=True)

    def _session_path(self, session_id: str, *, archived: bool = False) -> Path:
        if archived:
            return self.archived_sessions_dir / f"{session_id}.json"
        return self.sessions_dir / f"{session_id}.json"

    def _iter_session_paths(self, *, archived: bool = False) -> list[Path]:
        root = self.archived_sessions_dir if archived else self.sessions_dir
        return sorted(
            [path for path in root.glob("*.json") if path.is_file()],
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )

    @staticmethod
    def _now() -> float:
        return time.time()

    def _default_payload(self, title: str = "New Session") -> dict[str, Any]:
        now = self._now()
        return {
            "title": title,
            "created_at": now,
            "updated_at": now,
            "compressed_context": "",
        }

    def _write_json_file(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f"{path.suffix}.tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp.replace(path)

    def _read_session_payload(
        self, path: Path, *, session_id: str, archived: bool
    ) -> dict[str, Any]:
        if not path.exists():
            label = "Archived session" if archived else "Session"
            raise FileNotFoundError(f"{label} not found: {session_id}")

        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            raise LegacySessionStateError(
                f"Session uses unsupported legacy conversation format: {session_id}"
            )
        if not isinstance(raw, dict):
            raise LegacySessionStateError(
                f"Session metadata is invalid or unsupported: {session_id}"
            )
        if isinstance(raw.get("messages"), list) and raw.get("messages"):
            raise LegacySessionStateError(
                f"Session metadata contains unsupported legacy conversation messages: {session_id}"
            )
        if raw.get("live_response") is not None:
            raise LegacySessionStateError(
                f"Session metadata contains unsupported legacy live response state: {session_id}"
            )
        return raw

    async def create_session(
        self,
        session_id: str,
        *,
        title: str = "New Session",
        archived: bool = False,
    ) -> dict[str, Any]:
        async with self._lock:
            payload = self._default_payload(title.strip() or "New Session")
            path = self._session_path(session_id, archived=archived)
            self._write_json_file(path, payload)
            return payload

    async def load_existing_session(
        self, session_id: str, *, archived: bool = False
    ) -> dict[str, Any]:
        async with self._lock:
            path = self._session_path(session_id, archived=archived)
            return self._read_session_payload(
                path, session_id=session_id, archived=archived
            )

    async def load_session(
        self, session_id: str, *, archived: bool = False
    ) -> dict[str, Any]:
        async with self._lock:
            path = self._session_path(session_id, archived=archived)
            if not path.exists():
                if archived:
                    raise FileNotFoundError(f"Archived session not found: {session_id}")
                payload = self._default_payload()
                self._write_json_file(path, payload)
                return payload
            return self._read_session_payload(
                path, session_id=session_id, archived=archived
            )

    async def save_session(
        self, session_id: str, payload: dict[str, Any], *, archived: bool = False
    ) -> None:
        async with self._lock:
            payload["updated_at"] = self._now()
            path = self._session_path(session_id, archived=archived)
            self._write_json_file(path, payload)

    async def list_sessions(self, *, scope: str = "active") -> list[dict[str, Any]]:
        include_active = scope in {"active", "all"}
        include_archived = scope in {"archived", "all"}
        items: list[dict[str, Any]] = []
        if include_active:
            for path in self._iter_session_paths(archived=False):
                session_id = path.stem
                payload = self._read_session_payload(
                    path, session_id=session_id, archived=False
                )
                items.append(
                    {
                        "session_id": session_id,
                        "title": str(payload.get("title", "New Session")),
                        "created_at": float(payload.get("created_at", 0)),
                        "updated_at": float(payload.get("updated_at", 0)),
                        "archived": False,
                    }
                )
        if include_archived:
            for path in self._iter_session_paths(archived=True):
                session_id = path.stem
                payload = self._read_session_payload(
                    path, session_id=session_id, archived=True
                )
                items.append(
                    {
                        "session_id": session_id,
                        "title": str(payload.get("title", "New Session")),
                        "created_at": float(payload.get("created_at", 0)),
                        "updated_at": float(payload.get("updated_at", 0)),
                        "archived": True,
                    }
                )
        items.sort(key=lambda item: item["updated_at"], reverse=True)
        return items

    async def rename_session(self, session_id: str, title: str) -> dict[str, Any]:
        session = await self.load_session(session_id)
        session["title"] = title.strip()
        await self.save_session(session_id, session)
        return session

    async def update_title(self, session_id: str, title: str) -> None:
        session = await self.load_session(session_id)
        session["title"] = title.strip() or session.get("title", "New Session")
        await self.save_session(session_id, session)

    async def delete_session(self, session_id: str, *, archived: bool = False) -> bool:
        async with self._lock:
            path = self._session_path(session_id, archived=archived)
            if not path.exists():
                return False
            path.unlink()
            return True

    async def archive_session(self, session_id: str) -> bool:
        async with self._lock:
            source = self._session_path(session_id, archived=False)
            target = self._session_path(session_id, archived=True)
            if not source.exists():
                return False
            payload = self._read_session_payload(
                source, session_id=session_id, archived=False
            )
            payload["archived_at"] = self._now()
            self._write_json_file(target, payload)
            source.unlink()
            return True

    async def restore_session(self, session_id: str) -> bool:
        async with self._lock:
            source = self._session_path(session_id, archived=True)
            target = self._session_path(session_id, archived=False)
            if not source.exists():
                return False
            payload = self._read_session_payload(
                source, session_id=session_id, archived=True
            )
            payload.pop("archived_at", None)
            self._write_json_file(target, payload)
            source.unlink()
            return True

    async def get_compressed_context(self, session_id: str) -> str:
        session = await self.load_session(session_id)
        return str(session.get("compressed_context", "")).strip()
