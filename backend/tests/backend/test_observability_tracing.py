from __future__ import annotations

import sys
import types

from observability import tracing


def test_build_optional_callbacks_disabled_by_langsmith_flag(monkeypatch):
    monkeypatch.setenv("OBS_TRACING_PROVIDER", "langsmith")
    monkeypatch.setenv("LANGSMITH_TRACING", "false")

    callbacks = tracing.build_optional_callbacks(run_id="run-1")
    assert callbacks == []


def test_build_optional_callbacks_disabled_by_global_override(monkeypatch):
    monkeypatch.setenv("OBS_TRACING_PROVIDER", "langsmith")
    monkeypatch.setenv("OBS_TRACING_ENABLED", "0")
    monkeypatch.setenv("LANGSMITH_TRACING", "true")

    callbacks = tracing.build_optional_callbacks(run_id="run-2")
    assert callbacks == []


def test_build_optional_callbacks_disabled_by_langchain_v2_flag(monkeypatch):
    monkeypatch.setenv("OBS_TRACING_PROVIDER", "langsmith")
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")

    callbacks = tracing.build_optional_callbacks(run_id="run-3")
    assert callbacks == []


def test_build_optional_callbacks_langsmith_enabled_with_stub(monkeypatch):
    monkeypatch.setenv("OBS_TRACING_PROVIDER", "langsmith")
    monkeypatch.setenv("LANGSMITH_TRACING", "true")

    fake_module = types.ModuleType("langchain_core.tracers")

    class FakeTracer:
        def __init__(self, project_name: str):
            self.project_name = project_name
            self.run_name = ""

    fake_module.LangChainTracer = FakeTracer
    monkeypatch.setitem(sys.modules, "langchain_core.tracers", fake_module)

    callbacks = tracing.build_optional_callbacks(run_id="run-4")
    assert len(callbacks) == 1
    tracer = callbacks[0]
    assert getattr(tracer, "run_name", "") == "run-4"
