from __future__ import annotations

import pytest

from tools.sandbox import SandboxUnavailableError, resolve_sandbox


def test_resolve_sandbox_unsafe_mode(tmp_path):
    selection = resolve_sandbox(
        mode="unsafe_none",
        root_dir=tmp_path,
        require_sandbox=True,
        allow_network=False,
    )
    assert selection.backend_id == "unsafe_none"


def test_resolve_sandbox_hybrid_fail_closed(monkeypatch, tmp_path):
    import tools.sandbox as sandbox_module

    monkeypatch.setattr(sandbox_module.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(sandbox_module, "which", lambda _: None)

    with pytest.raises(SandboxUnavailableError):
        resolve_sandbox(
            mode="hybrid_auto",
            root_dir=tmp_path,
            require_sandbox=True,
            allow_network=False,
        )


def test_resolve_sandbox_hybrid_fallback_when_not_required(monkeypatch, tmp_path):
    import tools.sandbox as sandbox_module

    monkeypatch.setattr(sandbox_module.platform, "system", lambda: "Linux")
    monkeypatch.setattr(sandbox_module, "which", lambda _: None)

    selection = resolve_sandbox(
        mode="hybrid_auto",
        root_dir=tmp_path,
        require_sandbox=False,
        allow_network=False,
    )
    assert selection.backend_id == "unsafe_none"
