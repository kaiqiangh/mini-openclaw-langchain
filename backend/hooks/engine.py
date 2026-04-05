"""HookEngine stub — implementation deferred to Task 2."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hooks.types import HookConfig, HookEvent, HookResult


class HookEngine:
    """Stub HookEngine — lifecycle hook dispatcher.

    Full implementation will follow in:
    Task 2: Hook Registry & Loader
    Task 3: Sync Veto + Async Side-Effects
    Task 4: Tool Call Interception
    Task 5: Prompt Interception
    Task 6: Pre-Run Setup
    """

    def __init__(self) -> None:
        pass
