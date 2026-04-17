"""CompactionPipeline: Budget-aware message compaction with checkpoint/rewind."""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    messages_from_dict,
    messages_to_dict,
)
from pydantic import BaseModel, Field

# Token counting — use tiktoken if available, fallback to heuristic
try:
    import tiktoken
    _ENCODER = tiktoken.encoding_for_model("gpt-4o")

    def count_tokens(text: str) -> int:
        if not text:
            return 0
        return len(_ENCODER.encode(text))
except ImportError:
    def count_tokens(text: str) -> int:
        # ~4 chars per token heuristic
        if not text:
            return 0
        return max(1, len(text) // 4)


_MODEL_WINDOWS: dict[str, int] = {
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "claude-sonnet": 200_000,
    "claude-sonnet-4": 200_000,
    "qwen-plus": 131_072,
    "deepseek-chat": 65_536,
}


class CompactionSummary(BaseModel):
    summary: str = ""
    key_decisions: list[str] = Field(default_factory=list)
    key_facts: list[str] = Field(default_factory=list)
    open_threads: list[str] = Field(default_factory=list)
    tool_usage_summary: list[dict[str, str]] = Field(default_factory=list)


@dataclass
class CompactResult:
    messages: list[BaseMessage]
    summary: CompactionSummary | None
    checkpoint_id: str | None
    was_compacted: bool


class CompactionPipeline:
    """Compaction pipeline with budget check, checkpoint, summarize, distill, drop."""

    def __init__(
        self,
        *,
        model_name: str = "gpt-4o",
        budget_factor: float = 0.85,
        checkpoint_dir: Path | None = None,
    ) -> None:
        self.model_name = model_name
        self.budget_factor = budget_factor
        self.checkpoint_dir = checkpoint_dir

    def compute_budget(self) -> int:
        """Compute compaction budget (80% of context window)."""
        window = _MODEL_WINDOWS.get(self.model_name, 128_000)
        return int(window * 0.80)

    def count_messages_tokens(self, messages: list[BaseMessage]) -> int:
        """Count tokens across all messages."""
        total = 0
        for msg in messages:
            content = getattr(msg, "content", "")
            if isinstance(content, str):
                total += count_tokens(content)
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and "text" in item:
                        total += count_tokens(item["text"])
        return total

    def needs_compaction(self, messages: list[BaseMessage], token_count: int | None = None) -> tuple[bool, int]:
        """Check if messages exceed the compaction threshold."""
        budget = self.compute_budget()
        threshold = int(budget * self.budget_factor)
        if token_count is None:
            token_count = self.count_messages_tokens(messages)
        return token_count > threshold, budget

    @staticmethod
    def _checkpoint_owned_by(
        data: dict[str, Any],
        *,
        agent_id: str | None = None,
        session_id: str | None = None,
    ) -> bool:
        if agent_id is None and session_id is None:
            return True
        stored_agent_id = str(data.get("agent_id", "")).strip()
        stored_session_id = str(data.get("session_id", "")).strip()
        if not stored_agent_id or not stored_session_id:
            return False
        return stored_agent_id == (agent_id or "") and stored_session_id == (
            session_id or ""
        )

    async def create_checkpoint(
        self,
        messages: list[BaseMessage],
        run_id: str,
        step: int,
        *,
        agent_id: str | None = None,
        session_id: str | None = None,
    ) -> str:
        """Save a checkpoint snapshot of messages."""
        cp_id = f"ckpt_{run_id[:8]}_{step:04d}_{uuid.uuid4().hex[:6]}"
        if self.checkpoint_dir:
            self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
            cp_path = self.checkpoint_dir / f"{cp_id}.json"
            data = {
                "checkpoint_id": cp_id,
                "run_id": run_id,
                "step": step,
                "messages": messages_to_dict(messages),
            }
            if agent_id:
                data["agent_id"] = agent_id
            if session_id:
                data["session_id"] = session_id
            cp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return cp_id

    async def load_checkpoint(
        self,
        checkpoint_id: str,
        *,
        agent_id: str | None = None,
        session_id: str | None = None,
    ) -> list[BaseMessage]:
        """Load messages from a checkpoint."""
        if not self.checkpoint_dir:
            raise RuntimeError("No checkpoint directory configured")
        for f in self.checkpoint_dir.glob(f"{checkpoint_id}*.json"):
            data = json.loads(f.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                continue
            if not self._checkpoint_owned_by(
                data, agent_id=agent_id, session_id=session_id
            ):
                continue
            return messages_from_dict(data["messages"])
        raise FileNotFoundError(f"Checkpoint not found: {checkpoint_id}")

    async def list_checkpoints(
        self,
        *,
        agent_id: str | None = None,
        session_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """List all available checkpoints."""
        if not self.checkpoint_dir or not self.checkpoint_dir.exists():
            return []
        results = []
        for f in sorted(self.checkpoint_dir.glob("ckpt_*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    continue
                if not self._checkpoint_owned_by(
                    data, agent_id=agent_id, session_id=session_id
                ):
                    continue
                results.append({
                    "checkpoint_id": data["checkpoint_id"],
                    "run_id": data["run_id"],
                    "step": data["step"],
                    "message_count": len(data.get("messages", [])),
                })
                stored_agent_id = str(data.get("agent_id", "")).strip()
                stored_session_id = str(data.get("session_id", "")).strip()
                if stored_agent_id:
                    results[-1]["agent_id"] = stored_agent_id
                if stored_session_id:
                    results[-1]["session_id"] = stored_session_id
            except (json.JSONDecodeError, KeyError):
                continue
        return results

    # ── LLM Summarize (overridden by external pipeline wiring) ──

    async def llm_summarize(self, messages: list[BaseMessage]) -> CompactionSummary:
        """Default: raises. Must be bound with LCEL pipeline before use."""
        raise NotImplementedError(
            "llm_summarize must be bound with an LCEL pipeline. "
            "Use build_summarize_pipeline() from lcel_compaction.py and "
            "assign it to the pipeline before use."
        )

    async def distill(self, summary: CompactionSummary, memory_file: Path) -> None:
        """Append distilled facts to MEMORY.md."""
        if not memory_file.exists():
            memory_file.parent.mkdir(parents=True, exist_ok=True)
            memory_file.write_text("# Memory\n\n")

        import datetime
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
        lines = [
            f"\n--- Compaction {timestamp} ---\n",
            f"**Summary**: {summary.summary}\n",
        ]
        if summary.key_decisions:
            lines.append("**Key Decisions**:\n")
            for d in summary.key_decisions:
                lines.append(f"- {d}\n")
        if summary.key_facts:
            lines.append("**Key Facts**:\n")
            for f_ in summary.key_facts:
                lines.append(f"- {f_}\n")
        if summary.open_threads:
            lines.append("**Open Threads**:\n")
            for t in summary.open_threads:
                lines.append(f"- {t}\n")
        lines.append("\n")

        with open(memory_file, "a", encoding="utf-8") as fh:
            fh.writelines(lines)

    def drop(
        self,
        messages: list[BaseMessage],
        summary_text: str,
        keep_last: int = 4,
    ) -> tuple[list[BaseMessage], list[BaseMessage]]:
        """Drop early messages, keep system prompt + recent K messages."""
        system_msgs = [m for m in messages if isinstance(m, SystemMessage)]
        non_system = [m for m in messages if not isinstance(m, SystemMessage)]

        if keep_last > 0:
            keep = non_system[-keep_last:]
            dropped = non_system[:-keep_last]
        else:
            keep = []
            dropped = non_system

        remaining = list(system_msgs)
        if summary_text:
            remaining.append(HumanMessage(content=f"[Previous conversation summary: {summary_text}]"))
        remaining.extend(keep)

        return remaining, dropped

    async def compact_round(
        self,
        messages: list[BaseMessage],
        run_id: str = "",
        step: int = 0,
        keep_last: int = 4,
        summarize_fn=None,
        agent_id: str | None = None,
        session_id: str | None = None,
    ) -> CompactResult:
        """Execute one full compaction round."""
        needs, budget = self.needs_compaction(messages)
        if not needs:
            return CompactResult(messages=messages, summary=None, checkpoint_id=None, was_compacted=False)

        # Checkpoint
        checkpoint_id = await self.create_checkpoint(
            messages,
            run_id=run_id,
            step=step,
            agent_id=agent_id,
            session_id=session_id,
        )

        # Summarize
        summary: CompactionSummary | None = None
        summary_text = ""
        try:
            if summarize_fn is not None:
                summary = await summarize_fn(messages)
            else:
                summary = await self.llm_summarize(messages)
            summary_text = summary.summary if summary else ""
        except Exception:
            summary_text = "[Conversation summarized (LLM unavailable, proceeding with drop-only)]"

        # Drop
        remaining, dropped = self.drop(messages, summary_text, keep_last=keep_last)

        return CompactResult(
            messages=remaining,
            summary=summary,
            checkpoint_id=checkpoint_id,
            was_compacted=True,
        )
