from __future__ import annotations

import hashlib
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config import InjectionMode, RuntimeConfig


RAG_GUIDANCE = """[Memory Retrieval Mode]
Long-term memory is injected dynamically via retrieval for this request.
Use the retrieval context as temporary input and do not assume it is persisted.
"""


@dataclass
class PromptPack:
    prompt: str
    digest: str
    source_mtimes: dict[str, float]
    truncated_files: list[str]


class PromptBuilder:
    def __init__(self, max_cache_entries: int = 128) -> None:
        self._max_cache_entries = max(1, int(max_cache_entries))
        self._cache: OrderedDict[str, PromptPack] = OrderedDict()

    @staticmethod
    def truncate_component(text: str, max_chars: int = 20000) -> tuple[str, bool]:
        if len(text) <= max_chars:
            return text, False
        return text[:max_chars] + "\n...[truncated]", True

    @staticmethod
    def _read_or_missing(path: Path) -> tuple[str, bool, bool]:
        if not path.exists():
            return f"[MISSING FILE: {path}]", False, True
        text = path.read_text(encoding="utf-8")
        return text, False, False

    def _build_sections(
        self, base_dir: Path, rag_mode: bool
    ) -> list[tuple[str, str, str]]:
        components: list[tuple[str, str, Path | None]] = [
            ("Skills Snapshot", "SKILLS_SNAPSHOT.md", base_dir / "SKILLS_SNAPSHOT.md"),
            ("Soul", "workspace/SOUL.md", base_dir / "workspace" / "SOUL.md"),
            (
                "Identity",
                "workspace/IDENTITY.md",
                base_dir / "workspace" / "IDENTITY.md",
            ),
            ("User Profile", "workspace/USER.md", base_dir / "workspace" / "USER.md"),
            (
                "Heartbeat Guide",
                "workspace/HEARTBEAT.md",
                base_dir / "workspace" / "HEARTBEAT.md",
            ),
            (
                "Agents Guide",
                "workspace/AGENTS.md",
                base_dir / "workspace" / "AGENTS.md",
            ),
        ]

        if rag_mode:
            components.append(("Long-term Memory", "memory/MEMORY.md", None))
        else:
            components.append(
                (
                    "Long-term Memory",
                    "memory/MEMORY.md",
                    base_dir / "memory" / "MEMORY.md",
                )
            )

        sections: list[tuple[str, str, str]] = []
        for label, rel_path, abs_path in components:
            if rag_mode and rel_path == "memory/MEMORY.md":
                sections.append((label, rel_path, RAG_GUIDANCE.strip()))
                continue

            assert abs_path is not None
            content, _, missing = self._read_or_missing(abs_path)
            if missing:
                content = f"[MISSING FILE: {rel_path}]"
            sections.append((label, rel_path, content))

        return sections

    @staticmethod
    def _digest(parts: list[str]) -> str:
        hasher = hashlib.sha256()
        for item in parts:
            hasher.update(item.encode("utf-8"))
        return hasher.hexdigest()

    def build_system_prompt(
        self,
        base_dir: Path,
        runtime: RuntimeConfig,
        rag_mode: bool,
        is_first_turn: bool,
    ) -> PromptPack:
        if (
            runtime.injection_mode == InjectionMode.FIRST_TURN_ONLY
            and not is_first_turn
        ):
            empty_pack = PromptPack(
                prompt="", digest="", source_mtimes={}, truncated_files=[]
            )
            return empty_pack

        sections = self._build_sections(base_dir=base_dir, rag_mode=rag_mode)

        source_mtimes: dict[str, float] = {}
        source_sizes: dict[str, int] = {}
        for _, rel_path, _ in sections:
            abs_path = base_dir / rel_path
            try:
                stat = abs_path.stat()
            except FileNotFoundError:
                source_mtimes[rel_path] = -1.0
                source_sizes[rel_path] = -1
            else:
                source_mtimes[rel_path] = stat.st_mtime
                source_sizes[rel_path] = stat.st_size

        cache_key = self._digest(
            [
                str(base_dir.resolve()),
                str(rag_mode),
                runtime.injection_mode.value,
                str(runtime.bootstrap_max_chars),
                str(runtime.bootstrap_total_max_chars),
                *(
                    f"{rel_path}:{source_mtimes.get(rel_path, -1.0)}:{source_sizes.get(rel_path, -1)}:{self._digest([content])}"
                    for _, rel_path, content in sections
                ),
            ]
        )

        cached = self._cache.pop(cache_key, None)
        if cached is not None:
            self._cache[cache_key] = cached
            return cached

        rendered_parts: list[str] = []
        truncated_files: list[str] = []

        for label, rel_path, content in sections:
            content, was_truncated = self.truncate_component(
                content, runtime.bootstrap_max_chars
            )
            if was_truncated:
                truncated_files.append(rel_path)
            rendered_parts.append(f"<!-- {label} -->\n{content}")

        prompt = "\n\n".join(rendered_parts)
        if len(prompt) > runtime.bootstrap_total_max_chars:
            prompt = (
                prompt[: runtime.bootstrap_total_max_chars] + "\n...[truncated_total]"
            )

        digest = self._digest([prompt])
        pack = PromptPack(
            prompt=prompt,
            digest=digest,
            source_mtimes=source_mtimes,
            truncated_files=truncated_files,
        )
        self._cache[cache_key] = pack
        while len(self._cache) > self._max_cache_entries:
            self._cache.popitem(last=False)
        return pack
