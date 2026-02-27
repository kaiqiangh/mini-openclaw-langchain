from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from api.errors import ApiError
from graph.agent import AgentManager

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    agent_id: str = Field(default="default", min_length=1, max_length=64)
    stream: bool = True


_agent_manager: AgentManager | None = None


def set_agent_manager(agent_manager: AgentManager) -> None:
    global _agent_manager
    _agent_manager = agent_manager


def _require_agent_manager() -> AgentManager:
    if _agent_manager is None or _agent_manager.session_manager is None:
        raise ApiError(status_code=500, code="not_initialized", message="Agent manager is not initialized")
    return _agent_manager


@router.post("/chat")
async def chat(request: ChatRequest) -> Any:
    agent = _require_agent_manager()
    try:
        runtime = agent.get_runtime(request.agent_id)
        session_manager = runtime.session_manager
    except ValueError as exc:
        raise ApiError(status_code=400, code="invalid_request", message=str(exc)) from exc

    session = session_manager.load_session(request.session_id)
    is_first_turn = len(session.get("messages", [])) == 0
    history = session_manager.load_session_for_agent(request.session_id)

    if not request.stream:
        result = await agent.run_once(
            message=request.message,
            history=history,
            session_id=request.session_id,
            output_format="text",
            trigger_type="chat",
            agent_id=request.agent_id,
        )
        text = str(result.get("text", ""))
        usage = result.get("usage", {})
        session_manager.save_message(request.session_id, "user", request.message)
        session_manager.save_message(request.session_id, "assistant", text)
        return {
            "data": {
                "content": text,
                "session_id": request.session_id,
                "agent_id": request.agent_id,
                "usage": usage,
            }
        }

    async def event_generator():
        assistant_segments: list[dict[str, Any]] = []
        current_content = ""
        current_tool_calls: list[dict[str, Any]] = []
        pending_title: str | None = None

        async for event in agent.astream(
            message=request.message,
            history=history,
            session_id=request.session_id,
            is_first_turn=is_first_turn,
            trigger_type="chat",
            agent_id=request.agent_id,
        ):
            event_type = str(event.get("type", "message"))
            data = event.get("data", {})

            if event_type == "token":
                current_content += str(data.get("content", ""))

            if event_type == "tool_start":
                current_tool_calls.append(
                    {
                        "tool": data.get("tool", "tool"),
                        "input": data.get("input", {}),
                    }
                )

            if event_type == "tool_end" and current_tool_calls:
                current_tool_calls[-1]["output"] = data.get("output", "")

            if event_type == "new_response":
                if current_content.strip() or current_tool_calls:
                    assistant_segments.append(
                        {
                            "content": current_content.strip(),
                            "tool_calls": list(current_tool_calls),
                        }
                    )
                current_content = ""
                current_tool_calls = []

            if event_type == "done":
                if current_content.strip() or current_tool_calls:
                    assistant_segments.append(
                        {
                            "content": current_content.strip() or str(data.get("content", "")).strip(),
                            "tool_calls": list(current_tool_calls),
                        }
                    )

                session_manager.save_message(request.session_id, "user", request.message)
                if runtime.audit_store is not None:
                    runtime.audit_store.append_message_link(
                        run_id=None,
                        session_id=request.session_id,
                        role="user",
                        segment_index=0,
                        content=request.message,
                        details={"source": "chat_persist"},
                    )
                for idx, segment in enumerate(assistant_segments):
                    content = str(segment.get("content", "")).strip()
                    if not content:
                        continue
                    tool_calls = segment.get("tool_calls") or None
                    session_manager.save_message(request.session_id, "assistant", content, tool_calls=tool_calls)
                    if runtime.audit_store is not None:
                        runtime.audit_store.append_message_link(
                            run_id=None,
                            session_id=request.session_id,
                            role="assistant",
                            segment_index=idx,
                            content=content,
                            details={"tool_call_count": len(tool_calls or [])},
                        )

                if is_first_turn:
                    title = await agent.generate_title(request.message)
                    session_manager.update_title(request.session_id, title)
                    pending_title = title

            yield {
                "event": event_type,
                "data": json.dumps(data, ensure_ascii=False),
            }

            if event_type == "done" and pending_title:
                yield {
                    "event": "title",
                    "data": json.dumps(
                        {"session_id": request.session_id, "agent_id": request.agent_id, "title": pending_title},
                        ensure_ascii=False,
                    ),
                }

    return EventSourceResponse(event_generator())
