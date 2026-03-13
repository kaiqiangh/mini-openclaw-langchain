from __future__ import annotations

from typing import Any, cast

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable, RunnableLambda

from graph.runtime_types import ToolCapableChatModel
from graph.skill_selector import SelectedSkill, SkillSelector


class RuntimeLcelPipelines:
    @staticmethod
    def _coerce_selected_skill(value: Any) -> SelectedSkill | None:
        if isinstance(value, SelectedSkill):
            return value
        if not isinstance(value, dict):
            return None
        name = str(value.get("name", "")).strip()
        location = str(value.get("location", "")).strip()
        description = str(value.get("description", "")).strip()
        reason = str(value.get("reason", "")).strip()
        if not name or not location:
            return None
        try:
            score = int(value.get("score", 0))
        except Exception:
            score = 0
        return SelectedSkill(
            name=name,
            location=location,
            description=description,
            reason=reason,
            score=score,
        )

    @staticmethod
    def _build_system_prompt(payload: dict[str, Any]) -> str:
        base_prompt = str(payload.get("base_system_prompt", "")).strip()
        selected_skills = payload.get("selected_skills", [])
        normalized_skills = [
            skill
            for item in selected_skills
            if (skill := RuntimeLcelPipelines._coerce_selected_skill(item)) is not None
        ]
        selected_section = SkillSelector.render_prompt_section(normalized_skills)
        if not selected_section:
            return base_prompt
        if not base_prompt:
            return selected_section
        return f"{selected_section}\n\n{base_prompt}"

    @staticmethod
    def _build_request_messages(payload: dict[str, Any]) -> list[BaseMessage]:
        history = payload.get("history", [])
        turn_messages = payload.get("turn_messages", [])
        message = str(payload.get("message", ""))
        compressed_context = str(payload.get("compressed_context", "") or "").strip()
        rag_context = str(payload.get("rag_context", "") or "").strip()

        built: list[BaseMessage] = []
        if compressed_context:
            built.append(
                AIMessage(
                    content=f"[Summary of Earlier Conversation]\n{compressed_context}"
                )
            )
        if isinstance(history, list):
            for item in history:
                if not isinstance(item, dict):
                    continue
                role = str(item.get("role", "user")).strip().lower()
                content = str(item.get("content", "")).strip()
                if not content:
                    continue
                if role == "assistant":
                    built.append(AIMessage(content=content))
                else:
                    built.append(HumanMessage(content=content))

        if rag_context:
            built.append(SystemMessage(content=rag_context))
        if isinstance(turn_messages, list):
            built.extend(item for item in turn_messages if isinstance(item, BaseMessage))
        if message:
            built.append(HumanMessage(content=message))
        return built

    @staticmethod
    def _build_model_input(payload: dict[str, Any]) -> list[BaseMessage]:
        system_prompt = str(payload.get("system_prompt", "")).strip()
        messages = payload.get("messages", [])
        built: list[BaseMessage] = []
        if system_prompt:
            built.append(SystemMessage(content=system_prompt))
        if isinstance(messages, list):
            built.extend(item for item in messages if isinstance(item, BaseMessage))
        return built

    def system_prompt_chain(self) -> Runnable[Any, str]:
        return RunnableLambda(self._build_system_prompt)

    def message_chain(self) -> Runnable[Any, list[BaseMessage]]:
        return RunnableLambda(self._build_request_messages)

    def model_chain(
        self, *, llm: ToolCapableChatModel, tools: list[Any]
    ) -> Runnable[Any, Any]:
        active_llm: Runnable[Any, Any] = (
            llm.bind_tools(tools) if tools else cast(Runnable[Any, Any], llm)
        )
        return RunnableLambda(self._build_model_input) | active_llm

    def title_chain(self, *, llm: Any) -> Runnable[Any, str]:
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "human",
                    "Generate a short session title in plain English, at most 10 words. "
                    "No quotes and no trailing punctuation. Return only the title.\n"
                    "Content: {seed_text}",
                )
            ]
        )
        return prompt | llm | StrOutputParser()

    def summary_chain(self, *, llm: Any) -> Runnable[Any, str]:
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "human",
                    "Summarize the following conversation in under 500 characters. "
                    "Preserve key conclusions, user preferences, and unfinished tasks.\n"
                    "{corpus}",
                )
            ]
        )
        return prompt | llm | StrOutputParser()

    @staticmethod
    def structured_answer(answer: str) -> dict[str, str]:
        return {"answer": answer}
