from __future__ import annotations

from typing import Any


class StreamOrchestrator:
    @staticmethod
    def as_text(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return " ".join(str(item) for item in content)
        return str(content)

    @staticmethod
    def extract_token_text(token: Any) -> list[str]:
        texts: list[str] = []

        blocks = getattr(token, "content_blocks", None)
        if isinstance(blocks, list):
            for block in blocks:
                if not isinstance(block, dict):
                    continue
                btype = str(block.get("type", ""))
                if btype in {"text", "text_chunk"}:
                    text = block.get("text") or block.get("content") or ""
                    if text:
                        texts.append(str(text))

        if not texts:
            content = getattr(token, "content", None)
            if isinstance(content, str) and content:
                texts.append(content)

        return texts

    @staticmethod
    def extract_reasoning_text(message: Any) -> list[str]:
        texts: list[str] = []
        blocks = getattr(message, "content_blocks", None)
        if not isinstance(blocks, list):
            return texts

        for block in blocks:
            if not isinstance(block, dict):
                continue
            btype = str(block.get("type", "")).lower()
            if btype not in {
                "reasoning",
                "reasoning_chunk",
                "thinking",
                "thinking_chunk",
            }:
                continue
            text = (
                block.get("text")
                or block.get("content")
                or block.get("reasoning")
                or ""
            )
            if text:
                texts.append(str(text))
        return texts

    @staticmethod
    def diff_incremental(previous: str, current: str) -> str:
        if not current:
            return ""
        if not previous:
            return current
        if current.startswith(previous):
            return current[len(previous) :]
        if current == previous:
            return ""
        return current
