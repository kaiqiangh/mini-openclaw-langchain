from __future__ import annotations

from typing import TYPE_CHECKING, Any

__all__ = ["AgentManager", "MemoryIndexer", "PromptBuilder", "SessionManager"]

if TYPE_CHECKING:
    from .agent import AgentManager
    from .memory_indexer import MemoryIndexer
    from .prompt_builder import PromptBuilder
    from .session_manager import SessionManager


def __getattr__(name: str) -> Any:
    # Lazy exports avoid import cycles between `tools` and `graph` modules.
    if name == "AgentManager":
        from .agent import AgentManager

        return AgentManager
    if name == "MemoryIndexer":
        from .memory_indexer import MemoryIndexer

        return MemoryIndexer
    if name == "PromptBuilder":
        from .prompt_builder import PromptBuilder

        return PromptBuilder
    if name == "SessionManager":
        from .session_manager import SessionManager

        return SessionManager
    raise AttributeError(name)
