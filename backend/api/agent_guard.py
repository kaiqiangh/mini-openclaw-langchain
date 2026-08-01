from __future__ import annotations

from typing import Any

from api.errors import ApiError
from graph.agent import AgentManager


def require_existing_runtime(manager: AgentManager, agent_id: str) -> Any:
    normalize = getattr(manager, "_normalize_agent_id", None)
    try:
        normalized = normalize(agent_id) if callable(normalize) else agent_id.strip()
    except ValueError as exc:
        raise ApiError(status_code=400, code="invalid_request", message=str(exc)) from exc

    exists = getattr(manager, "agent_exists", None)
    if callable(exists):
        known = bool(exists(normalized))
    else:
        known = normalized in {
            str(row.get("agent_id", "")).strip()
            for row in manager.list_agents()
            if str(row.get("agent_id", "")).strip()
        }
    if not known:
        raise ApiError(status_code=404, code="not_found", message="Agent not found")

    try:
        return manager.get_runtime(normalized)
    except ValueError as exc:
        raise ApiError(status_code=400, code="invalid_request", message=str(exc)) from exc
