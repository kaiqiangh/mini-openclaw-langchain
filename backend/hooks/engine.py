"""HookEngine: Registry and Dispatcher for lifecycle hooks."""
from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import sys
import threading
from pathlib import Path
from typing import Any

from hooks.types import HookConfig, HookEvent, HookResult, HookType

logger = logging.getLogger(__name__)

# Module-level handler cache
_HANDLER_CACHE: dict[str, Any] = {}
_HANDLER_CACHE_MTIMES: dict[str, float] = {}


def _clear_handler_cache() -> None:
    """Clear the module-level handler cache and sys.modules entries."""
    for mod_name in list(_HANDLER_CACHE.keys()):
        if mod_name in sys.modules:
            del sys.modules[mod_name]
    _HANDLER_CACHE.clear()
    _HANDLER_CACHE_MTIMES.clear()


class HookEngine:
    """Manages hook registry and dispatch (sync + async)."""

    def __init__(self, *, agent_id: str, workspace_root: Path) -> None:
        self.agent_id = agent_id
        self.workspace_root = Path(workspace_root)
        self._hooks: dict[str, HookConfig] = {}
        self._config_path = self.workspace_root / "hooks.json"
        self.is_enabled = True

    # ── Registry ────────────────────────────────────────────────

    def load_config(self) -> None:
        """Load hooks from workspace hooks.json."""
        if not self._config_path.exists():
            self._hooks.clear()
            return
        try:
            text = self._config_path.read_text(encoding="utf-8")
            data = json.loads(text)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("[%s] Failed to load hooks.json: %s", self.agent_id, exc)
            self._hooks.clear()
            return

        raw_hooks = data.get("hooks", [])
        new_hooks: dict[str, HookConfig] = {}
        for entry in raw_hooks:
            try:
                config = HookConfig.from_dict(entry)
            except Exception as exc:
                logger.warning("[%s] Invalid hook config: %s", self.agent_id, exc)
                continue
            handler_path = self.workspace_root / config.handler
            if not handler_path.exists():
                continue
            new_hooks[config.id] = config
        self._hooks = new_hooks

    def add_hook(self, config: HookConfig) -> None:
        handler_path = self.workspace_root / config.handler
        if not handler_path.is_file():
            raise FileNotFoundError(f"Hook handler not found: {config.handler}")
        self._hooks[config.id] = config
        self._persist_config()

    def remove_hook(self, hook_id: str) -> bool:
        if hook_id in self._hooks:
            del self._hooks[hook_id]
            self._persist_config()
            return True
        return False

    def list_hooks(self) -> list[HookConfig]:
        return sorted(self._hooks.values(), key=lambda h: h.id)

    def get_hooks_by_type(self, hook_type: HookType) -> list[HookConfig]:
        return [h for h in self._hooks.values() if h.type == hook_type]

    def _persist_config(self) -> None:
        data = {
            "hooks": [
                {
                    "id": h.id,
                    "type": h.type.value,
                    "handler": h.handler,
                    "mode": h.mode,
                    "timeout_ms": h.timeout_ms,
                }
                for h in self._hooks.values()
            ]
        }
        self._config_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    # ── Dispatch: Sync ──────────────────────────────────────────

    def dispatch_sync(self, event: HookEvent) -> HookResult:
        """Dispatch hooks synchronously. Returns first deny result or allow."""
        hooks = self.get_hooks_by_type(HookType(event.hook_type))
        if not hooks:
            return HookResult(allow=True)

        for hook_config in hooks:
            try:
                handler = self._load_handler(hook_config.handler)
                result = self._invoke_with_timeout(handler, event, hook_config.timeout_ms)
                if not result.allow:
                    return result
                if result.modifications:
                    event.payload = {**event.payload, **result.modifications}
                # Keep last result (e.g., timeout reason) as fallback
                last_result = result
            except Exception as exc:
                logger.error("[%s] Hook '%s' exception: %s", self.agent_id, hook_config.id, exc)
                return HookResult(allow=False, reason=str(exc))

        # If last hook produced a non-empty reason (e.g. timeout), preserve it
        return last_result if last_result.reason else HookResult(allow=True)

    def _invoke_with_timeout(
        self, handler: Any, event: HookEvent, timeout_ms: int
    ) -> HookResult:
        result_container: list[HookResult | None] = [None]
        error_container: list[Exception | None] = [None]

        def _run() -> None:
            try:
                result_container[0] = handler.handle(event)
            except Exception as exc:
                error_container[0] = exc

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        thread.join(timeout=timeout_ms / 1000.0)

        if thread.is_alive():
            return HookResult(
                allow=True,
                reason=f"Hook timed out after {timeout_ms}ms (default allow)",
            )

        error = error_container[0]
        if error is not None:
            raise error

        return result_container[0] or HookResult(allow=True)

    # ── Dispatch: Async ─────────────────────────────────────────

    def dispatch_async(self, event: HookEvent) -> None:
        """Dispatch hooks asynchronously (fire-and-forget)."""
        hooks = self.get_hooks_by_type(HookType(event.hook_type))
        if not hooks:
            return
        for hook_config in hooks:
            try:
                handler = self._load_handler(hook_config.handler)
                asyncio.create_task(self._async_invoke(handler, event, hook_config))
            except Exception as exc:
                logger.error("[%s] Failed to dispatch async hook '%s': %s",
                    self.agent_id, hook_config.id, exc)

    async def _async_invoke(
        self, handler: Any, event: HookEvent, hook_config: HookConfig
    ) -> None:
        try:
            loop = asyncio.get_running_loop()
            await asyncio.wait_for(
                loop.run_in_executor(None, lambda: handler.handle(event)),
                timeout=hook_config.timeout_ms / 1000.0,
            )
        except asyncio.TimeoutError:
            logger.warning("[%s] Async hook '%s' timed out after %dms",
                self.agent_id, hook_config.id, hook_config.timeout_ms)
        except Exception as exc:
            logger.error("[%s] Async hook '%s' exception: %s",
                self.agent_id, hook_config.id, exc)

    # ── Handler Loading ──────────────────────────────────────────

    def _load_handler(self, handler_path: str) -> Any:
        """Load a Python module by relative path from workspace root."""
        full_path = (self.workspace_root / handler_path).resolve()
        module_name = f"_hook_{handler_path.replace('/', '_').replace('.py', '')}"

        existing = _HANDLER_CACHE.get(module_name)
        if existing is not None and _HANDLER_CACHE_MTIMES.get(module_name) == full_path.stat().st_mtime:
            return existing

        # Clean up stale sys.modules entry before reimporting
        if module_name in sys.modules:
            del sys.modules[module_name]

        spec = importlib.util.spec_from_file_location(module_name, str(full_path))
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load hook module: {handler_path}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        if hasattr(module, "handle"):
            _HANDLER_CACHE[module_name] = module
            _HANDLER_CACHE_MTIMES[module_name] = full_path.stat().st_mtime
            return module

        raise ImportError(f"Hook module {handler_path} must define a 'handle(event)' function")
