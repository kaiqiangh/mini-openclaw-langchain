from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any


class SessionManager:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self._lock = threading.RLock()
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
            "messages": [],
        }

    def load_session(
        self, session_id: str, *, archived: bool = False
    ) -> dict[str, Any]:
        with self._lock:
            path = self._session_path(session_id, archived=archived)
            if not path.exists():
                if archived:
                    raise FileNotFoundError(f"Archived session not found: {session_id}")
                payload = self._default_payload()
                path.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                return payload

            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                payload = self._default_payload()
                payload["messages"] = raw
                path.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                return payload
            return raw

    def save_session(
        self, session_id: str, payload: dict[str, Any], *, archived: bool = False
    ) -> None:
        with self._lock:
            payload["updated_at"] = self._now()
            path = self._session_path(session_id, archived=archived)
            path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

    def list_sessions(self, *, scope: str = "active") -> list[dict[str, Any]]:
        include_active = scope in {"active", "all"}
        include_archived = scope in {"archived", "all"}
        items: list[dict[str, Any]] = []
        if include_active:
            for path in self._iter_session_paths(archived=False):
                session_id = path.stem
                payload = self.load_session(session_id, archived=False)
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
                payload = self.load_session(session_id, archived=True)
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

    def rename_session(self, session_id: str, title: str) -> dict[str, Any]:
        session = self.load_session(session_id)
        session["title"] = title.strip()
        self.save_session(session_id, session)
        return session

    def update_title(self, session_id: str, title: str) -> None:
        session = self.load_session(session_id)
        session["title"] = title.strip() or session.get("title", "New Session")
        self.save_session(session_id, session)

    def delete_session(self, session_id: str, *, archived: bool = False) -> bool:
        path = self._session_path(session_id, archived=archived)
        if not path.exists():
            return False
        path.unlink()
        return True

    def archive_session(self, session_id: str) -> bool:
        source = self._session_path(session_id, archived=False)
        target = self._session_path(session_id, archived=True)
        if not source.exists():
            return False
        payload = self.load_session(session_id, archived=False)
        payload["archived_at"] = self._now()
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        source.unlink()
        return True

    def restore_session(self, session_id: str) -> bool:
        source = self._session_path(session_id, archived=True)
        target = self._session_path(session_id, archived=False)
        if not source.exists():
            return False
        payload = self.load_session(session_id, archived=True)
        payload.pop("archived_at", None)
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        source.unlink()
        return True

    def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> None:
        with self._lock:
            session = self.load_session(session_id)
            entry: dict[str, Any] = {"role": role, "content": content}
            if tool_calls:
                entry["tool_calls"] = tool_calls
            session.setdefault("messages", []).append(entry)
            self.save_session(session_id, session)

    def set_live_response(
        self,
        session_id: str,
        *,
        run_id: str,
        content: str,
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> None:
        with self._lock:
            session = self.load_session(session_id)
            payload: dict[str, Any] = {
                "run_id": run_id,
                "content": content,
                "updated_at": self._now(),
            }
            if tool_calls:
                payload["tool_calls"] = tool_calls
            session["live_response"] = payload
            self.save_session(session_id, session)

    def clear_live_response(self, session_id: str, run_id: str | None = None) -> None:
        with self._lock:
            session = self.load_session(session_id)
            live = session.get("live_response")
            if not isinstance(live, dict):
                return
            if run_id and str(live.get("run_id", "")).strip() != run_id.strip():
                return
            session.pop("live_response", None)
            self.save_session(session_id, session)

    @staticmethod
    def with_live_response(messages: list[dict[str, Any]], session: dict[str, Any]) -> list[dict[str, Any]]:
        merged = [dict(message) for message in messages]
        live = session.get("live_response")
        if not isinstance(live, dict):
            return merged
        content = str(live.get("content", "")).strip()
        tool_calls = live.get("tool_calls")
        if not content and not (
            isinstance(tool_calls, list) and len(tool_calls) > 0
        ):
            return merged

        entry: dict[str, Any] = {
            "role": "assistant",
            "content": content,
            "streaming": True,
        }
        if isinstance(tool_calls, list) and tool_calls:
            entry["tool_calls"] = tool_calls
        run_id = str(live.get("run_id", "")).strip()
        if run_id:
            entry["run_id"] = run_id
        merged.append(entry)
        return merged

    def get_compressed_context(self, session_id: str) -> str:
        session = self.load_session(session_id)
        return str(session.get("compressed_context", "")).strip()

    def load_session_for_agent(self, session_id: str) -> list[dict[str, Any]]:
        session = self.load_session(session_id)
        messages: list[dict[str, Any]] = list(session.get("messages", []))

        merged: list[dict[str, Any]] = []
        for msg in messages:
            if (
                merged
                and msg.get("role") == "assistant"
                and merged[-1].get("role") == "assistant"
            ):
                merged[-1]["content"] = (
                    str(merged[-1].get("content", ""))
                    + "\n"
                    + str(msg.get("content", ""))
                ).strip()
                continue
            merged.append(dict(msg))

        compressed = self.get_compressed_context(session_id)
        if compressed:
            merged.insert(
                0,
                {
                    "role": "assistant",
                    "content": f"[Summary of Earlier Conversation]\n{compressed}",
                },
            )

        return merged

    def compress_history(self, session_id: str, summary: str, n: int) -> dict[str, int]:
        session = self.load_session(session_id)
        messages = session.get("messages", [])
        archive_count = min(max(0, n), len(messages))

        to_archive = messages[:archive_count]
        remain = messages[archive_count:]

        if archive_count > 0:
            archive_path = self.archive_dir / f"{session_id}_{int(self._now())}.json"
            archive_path.write_text(
                json.dumps(to_archive, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

        prior = str(session.get("compressed_context", "")).strip()
        if prior and summary.strip():
            session["compressed_context"] = f"{prior}\n---\n{summary.strip()}"
        elif summary.strip():
            session["compressed_context"] = summary.strip()

        session["messages"] = remain
        self.save_session(session_id, session)

        return {"archived_count": archive_count, "remaining_count": len(remain)}
