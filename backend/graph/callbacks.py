from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from storage.run_store import AuditStore
from utils.redaction import redact_json_line


class AuditCallbackHandler(BaseCallbackHandler):
    def __init__(
        self,
        audit_file: Path,
        run_id: str,
        session_id: str,
        trigger_type: str,
        audit_store: AuditStore | None = None,
    ) -> None:
        super().__init__()
        self.audit_file = audit_file
        self.run_id = run_id
        self.session_id = session_id
        self.trigger_type = trigger_type
        self.audit_store = audit_store
        self.audit_file.parent.mkdir(parents=True, exist_ok=True)
        if self.audit_store is not None:
            self.audit_store.append_run(
                run_id=run_id,
                session_id=session_id,
                trigger_type=trigger_type,
                status="started",
            )

    def _write(self, event: str, payload: dict[str, Any]) -> None:
        row = {
            "timestamp_ms": int(time.time() * 1000),
            "event": event,
            "run_id": self.run_id,
            "session_id": self.session_id,
            "trigger_type": self.trigger_type,
            **payload,
        }
        with self.audit_file.open("a", encoding="utf-8") as fh:
            fh.write(redact_json_line(row) + "\n")
        if self.audit_store is not None:
            self.audit_store.append_step(
                run_id=self.run_id,
                session_id=self.session_id,
                trigger_type=self.trigger_type,
                event=event,
                details=payload,
            )

    def on_tool_start(self, serialized: dict[str, Any], input_str: str, **kwargs: Any) -> None:
        self._write(
            "tool_start",
            {
                "tool": serialized.get("name", "unknown"),
                "input": input_str,
            },
        )

    def on_tool_end(self, output: Any, **kwargs: Any) -> None:
        self._write(
            "tool_end",
            {
                "output": str(output)[:2000],
            },
        )

    def on_llm_start(self, serialized: dict[str, Any], prompts: list[str], **kwargs: Any) -> None:
        self._write(
            "llm_start",
            {
                "model": serialized.get("name", "unknown"),
                "prompt_count": len(prompts),
            },
        )

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        self._write(
            "llm_end",
            {
                "generation_count": len(getattr(response, "generations", [])),
            },
        )
        if self.audit_store is not None:
            self.audit_store.append_run(
                run_id=self.run_id,
                session_id=self.session_id,
                trigger_type=self.trigger_type,
                status="completed",
            )

    def on_llm_error(self, error: BaseException, **kwargs: Any) -> None:
        self._write(
            "llm_error",
            {
                "error": str(error),
            },
        )
        if self.audit_store is not None:
            self.audit_store.append_run(
                run_id=self.run_id,
                session_id=self.session_id,
                trigger_type=self.trigger_type,
                status="failed",
                details={"error": str(error)},
            )
