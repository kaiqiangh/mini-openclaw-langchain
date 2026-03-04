from __future__ import annotations

import importlib
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .base import ToolContext
from .contracts import ToolResult
from .path_guard import InvalidPathError, resolve_workspace_path
from .policy import PermissionLevel


@dataclass
class ReadPdfTool:
    root_dir: Path
    max_chars_default: int = 10000
    max_pages: int = 100

    name: str = "read_pdf"
    description: str = "Read text from PDF files in the workspace"
    permission_level: PermissionLevel = PermissionLevel.L0_READ

    @staticmethod
    def _normalize_pages(raw_pages: Any) -> tuple[list[int], str | None]:
        if raw_pages is None:
            return [], None
        if not isinstance(raw_pages, list):
            return [], "pages must be a list of 1-based page numbers"
        normalized: list[int] = []
        for value in raw_pages:
            try:
                page = int(value)
            except Exception:
                return [], "pages must contain integers"
            if page < 1:
                return [], "page numbers must be >= 1"
            normalized.append(page)
        return sorted(set(normalized)), None

    def run(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        _ = context
        started = time.monotonic()
        path = str(args.get("path", "")).strip()
        if not path:
            return ToolResult.failure(
                tool_name=self.name,
                code="E_INVALID_ARGS",
                message="Missing required 'path' argument",
                duration_ms=int((time.monotonic() - started) * 1000),
            )

        pages, page_error = self._normalize_pages(args.get("pages"))
        if page_error is not None:
            return ToolResult.failure(
                tool_name=self.name,
                code="E_INVALID_ARGS",
                message=page_error,
                duration_ms=int((time.monotonic() - started) * 1000),
            )

        max_chars = int(args.get("max_chars", self.max_chars_default))
        max_chars = max(1, max_chars)

        try:
            resolved = resolve_workspace_path(self.root_dir, path)
        except InvalidPathError as exc:
            return ToolResult.failure(
                tool_name=self.name,
                code="E_INVALID_PATH",
                message=str(exc),
                duration_ms=int((time.monotonic() - started) * 1000),
                retryable=False,
            )

        if not resolved.exists() or not resolved.is_file():
            return ToolResult.failure(
                tool_name=self.name,
                code="E_NOT_FOUND",
                message=f"File not found: {path}",
                duration_ms=int((time.monotonic() - started) * 1000),
                retryable=False,
            )

        if resolved.suffix.lower() != ".pdf":
            return ToolResult.failure(
                tool_name=self.name,
                code="E_INVALID_ARGS",
                message="path must point to a .pdf file",
                duration_ms=int((time.monotonic() - started) * 1000),
                retryable=False,
            )

        try:
            pypdf = importlib.import_module("pypdf")
            reader = pypdf.PdfReader(str(resolved))
        except ModuleNotFoundError:
            return ToolResult.failure(
                tool_name=self.name,
                code="E_INTERNAL",
                message="Missing optional dependency 'pypdf'. Install backend/requirements-pdf.txt",
                duration_ms=int((time.monotonic() - started) * 1000),
                retryable=False,
            )
        except Exception as exc:
            return ToolResult.failure(
                tool_name=self.name,
                code="E_IO",
                message=f"Failed to parse PDF: {exc}",
                duration_ms=int((time.monotonic() - started) * 1000),
                retryable=False,
            )

        total_pages = len(reader.pages)
        if total_pages <= 0:
            return ToolResult.success(
                tool_name=self.name,
                data={
                    "path": path,
                    "page_count": 0,
                    "pages_read": [],
                    "content": "",
                    "truncated": False,
                },
                duration_ms=int((time.monotonic() - started) * 1000),
            )

        selected = pages or list(range(1, total_pages + 1))
        if len(selected) > self.max_pages:
            return ToolResult.failure(
                tool_name=self.name,
                code="E_INVALID_ARGS",
                message=f"pages length exceeds max of {self.max_pages}",
                duration_ms=int((time.monotonic() - started) * 1000),
                retryable=False,
            )

        for page in selected:
            if page > total_pages:
                return ToolResult.failure(
                    tool_name=self.name,
                    code="E_INVALID_ARGS",
                    message=f"Requested page {page} exceeds total pages ({total_pages})",
                    duration_ms=int((time.monotonic() - started) * 1000),
                    retryable=False,
                )

        warnings: list[str] = []
        chunks: list[str] = []
        for page in selected:
            try:
                text = str(reader.pages[page - 1].extract_text() or "").strip()
            except Exception as exc:
                warnings.append(f"Failed to extract page {page}: {exc}")
                continue
            if text:
                chunks.append(f"[Page {page}]\n{text}")

        content = "\n\n".join(chunks).strip()
        truncated = False
        if len(content) > max_chars:
            content = content[:max_chars] + "\n...[truncated]"
            truncated = True

        return ToolResult.success(
            tool_name=self.name,
            data={
                "path": path,
                "page_count": total_pages,
                "pages_read": selected,
                "content": content,
                "truncated": truncated,
                "warnings": warnings,
            },
            duration_ms=int((time.monotonic() - started) * 1000),
            truncated=truncated,
            warnings=warnings,
        )
