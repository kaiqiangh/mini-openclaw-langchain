from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.skills_scanner import SkillMeta, scan_skills

_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{1,}")
_FRONTMATTER_PATTERN = re.compile(r"^---\s*\n.*?\n---\s*\n", re.DOTALL)
_STOPWORDS = {
    "a",
    "an",
    "and",
    "any",
    "are",
    "as",
    "at",
    "be",
    "by",
    "can",
    "for",
    "from",
    "get",
    "has",
    "have",
    "how",
    "i",
    "in",
    "into",
    "is",
    "it",
    "latest",
    "me",
    "my",
    "of",
    "on",
    "or",
    "our",
    "please",
    "show",
    "that",
    "the",
    "their",
    "them",
    "these",
    "this",
    "to",
    "today",
    "token",
    "tokens",
    "what",
    "which",
    "with",
    "you",
    "your",
}
_ALIAS_REPLACEMENTS = (
    ("binance smart chain", "bsc"),
    ("bnb smart chain", "bsc"),
    ("smart chain", "bsc"),
)


@dataclass(frozen=True)
class SelectedSkill:
    name: str
    location: str
    description: str
    reason: str
    score: int


@dataclass(frozen=True)
class _SkillDescriptor:
    name: str
    location: str
    description: str
    excerpt: str
    name_tokens: frozenset[str]
    body_tokens: frozenset[str]
    full_text: str


class SkillSelector:
    def __init__(self) -> None:
        self._descriptor_cache: dict[str, tuple[str, list[_SkillDescriptor]]] = {}

    @staticmethod
    def _normalize_text(value: str) -> str:
        lowered = value.lower().strip()
        for source, target in _ALIAS_REPLACEMENTS:
            lowered = lowered.replace(source, target)
        return lowered

    @staticmethod
    def _tokenize(value: str) -> set[str]:
        normalized = SkillSelector._normalize_text(value)
        tokens: set[str] = set()
        for raw in _TOKEN_PATTERN.findall(normalized):
            token = raw.lower().strip("._-")
            if token.endswith("s") and len(token) > 4:
                token = token[:-1]
            if len(token) < 3 or token in _STOPWORDS:
                continue
            tokens.add(token)
        return tokens

    @staticmethod
    def _build_excerpt(text: str) -> str:
        body = _FRONTMATTER_PATTERN.sub("", text, count=1)
        lines: list[str] = []
        for raw_line in body.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith(("#", "|", "```")):
                continue
            if set(line) <= {"-", "|", " "}:
                continue
            if line.startswith(("-", "*")):
                line = line[1:].strip()
            lines.append(line)
            if len(lines) >= 3:
                break
        excerpt = " ".join(lines)
        return excerpt[:280].strip()

    def _cache_key(self, base_dir: Path) -> str:
        skills_dir = base_dir / "skills"
        entries: list[str] = []
        for path in sorted(skills_dir.glob("*/SKILL.md")):
            try:
                entries.append(f"{path.name}:{path.stat().st_mtime_ns}")
            except FileNotFoundError:
                continue
        return "|".join(entries)

    def _load_descriptors(self, base_dir: Path) -> list[_SkillDescriptor]:
        cache_key = self._cache_key(base_dir)
        cached = self._descriptor_cache.get(str(base_dir))
        if cached is not None and cached[0] == cache_key:
            return cached[1]

        descriptors: list[_SkillDescriptor] = []
        for meta in scan_skills(base_dir):
            skill_path = base_dir / meta.location.lstrip("./")
            text = ""
            if skill_path.exists():
                text = skill_path.read_text(encoding="utf-8", errors="replace")
            excerpt = self._build_excerpt(text) if text else ""
            full_text = " ".join(
                part for part in [meta.name, meta.description, excerpt] if part.strip()
            )
            descriptors.append(
                _SkillDescriptor(
                    name=meta.name,
                    location=meta.location,
                    description=meta.description.strip(),
                    excerpt=excerpt,
                    name_tokens=frozenset(self._tokenize(meta.name)),
                    body_tokens=frozenset(self._tokenize(full_text)),
                    full_text=self._normalize_text(full_text),
                )
            )
        self._descriptor_cache[str(base_dir)] = (cache_key, descriptors)
        return descriptors

    @staticmethod
    def _recent_history_text(history: list[dict[str, Any]], limit: int = 6) -> str:
        parts: list[str] = []
        for item in history[-limit:]:
            role = str(item.get("role", "")).strip().lower()
            if role != "user":
                continue
            content = str(item.get("content", "")).strip()
            if content:
                parts.append(content)
        return "\n".join(parts)

    @staticmethod
    def _reason_for_terms(terms: set[str], *, explicit_name: bool) -> str:
        if explicit_name:
            return "explicitly named in the request"
        if not terms:
            return "matched the request context"
        ordered = ", ".join(sorted(terms)[:4])
        return f"matched terms: {ordered}"

    @staticmethod
    def _name_explicitly_mentioned(message_text: str, skill_name: str) -> bool:
        normalized_message = SkillSelector._normalize_text(message_text)
        normalized_name = SkillSelector._normalize_text(skill_name).replace("-", " ")
        if not normalized_name:
            return False
        return normalized_name in normalized_message.replace("-", " ")

    def select(
        self,
        *,
        base_dir: Path,
        message: str,
        history: list[dict[str, Any]],
        top_k: int = 3,
    ) -> list[SelectedSkill]:
        descriptors = self._load_descriptors(base_dir)
        if not descriptors:
            return []

        current_text = self._normalize_text(message)
        current_tokens = self._tokenize(message)
        history_text = self._recent_history_text(history)
        history_tokens = self._tokenize(history_text)

        matches: list[SelectedSkill] = []
        for descriptor in descriptors:
            explicit_name = self._name_explicitly_mentioned(current_text, descriptor.name)
            current_name_overlap = current_tokens & set(descriptor.name_tokens)
            current_body_overlap = current_tokens & set(descriptor.body_tokens)
            history_overlap = history_tokens & set(descriptor.body_tokens)

            score = 0
            if explicit_name:
                score += 40
            score += len(current_name_overlap) * 10
            score += len(current_body_overlap) * 4
            score += len(history_overlap) * 2

            if not explicit_name and score < 8:
                continue

            reason = self._reason_for_terms(
                current_name_overlap | current_body_overlap,
                explicit_name=explicit_name,
            )
            matches.append(
                SelectedSkill(
                    name=descriptor.name,
                    location=descriptor.location,
                    description=descriptor.description or descriptor.excerpt,
                    reason=reason,
                    score=score,
                )
            )

        matches.sort(key=lambda item: (-item.score, item.name.lower()))
        return matches[: max(1, top_k)]

    @staticmethod
    def render_prompt_section(selected_skills: list[SelectedSkill]) -> str:
        if not selected_skills:
            return ""

        lines = [
            "<!-- Selected Skills -->",
            "[Selected Skills For This Request]",
            "These skills were preselected from the workspace. Prefer them before generic web research when they fit.",
        ]
        for item in selected_skills:
            lines.append(f"- {item.name} ({item.location})")
            lines.append(f"  why: {item.reason}")
            if item.description:
                description = " ".join(item.description.split())
                lines.append(f"  description: {description[:320]}")
        return "\n".join(lines)
