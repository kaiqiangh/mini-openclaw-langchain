"""LCEL pipelines for compaction: summarize and distill."""
from __future__ import annotations

from typing import Any

from langchain_core.messages import BaseMessage
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from graph.compaction import CompactionSummary


SUMMARIZE_PROMPT = ChatPromptTemplate.from_messages([
    ("system", (
        "You are a conversation summarizer. Given a list of messages, "
        "produce a structured summary. Be concise but capture all key decisions, "
        "facts, and open threads. Return ONLY valid JSON."
    )),
    ("human", (
        "Messages to summarize:\n\n{messages_text}\n\n"
        "Return JSON matching this schema:\n"
        "{format_instructions}"
    )),
])


DISTILL_PROMPT = ChatPromptTemplate.from_messages([
    ("system", (
        "You are a memory distiller. Given a conversation summary, "
        "extract the most important facts and decisions that should be "
        "remembered long-term. Be selective — only capture what matters. "
        "Return ONLY valid JSON."
    )),
    ("human", (
        "Summary:\n{summary}\n\n"
        "Return JSON matching this schema:\n"
        "{format_instructions}"
    )),
])


def build_summarize_pipeline(llm: Any):
    """Returns an async callable: async(messages: list[BaseMessage]) -> CompactionSummary."""
    parser = JsonOutputParser(pydantic_object=CompactionSummary)

    def _messages_to_text(messages: list[BaseMessage]) -> str:
        parts = []
        for msg in messages:
            content = getattr(msg, "content", "")
            if isinstance(content, list):
                content = " ".join(
                    item.get("text", "") for item in content if isinstance(item, dict)
                )
            parts.append(f"[{getattr(msg, 'type', '?')}]: {content[:500]}")
        return "\n\n".join(parts)

    chain = SUMMARIZE_PROMPT | llm | parser

    async def summarize(messages: list[BaseMessage]) -> CompactionSummary:
        text = _messages_to_text(messages)
        result = await chain.ainvoke({
            "messages_text": text,
            "format_instructions": parser.get_format_instructions(),
        })
        return CompactionSummary(**result)

    return summarize


def build_distill_pipeline(llm: Any):
    """Returns an async callable that re-distills a summary into key facts."""
    parser = JsonOutputParser(pydantic_object=CompactionSummary)

    chain = DISTILL_PROMPT | llm | parser

    async def distill(summary_text: str) -> CompactionSummary:
        result = await chain.ainvoke({
            "summary": summary_text,
            "format_instructions": parser.get_format_instructions(),
        })
        return CompactionSummary(**result)

    return distill
