from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tools.sandbox import (
    SandboxUnavailableError,
    _darwin_profile,
    _linux_bwrap_command,
    resolve_sandbox,
)


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


def test_linux_bwrap_command_builds_private_workspace_mount(tmp_path):
    command = _linux_bwrap_command(
        root_dir=tmp_path,
        argv=["python3", "-V"],
        allow_network=False,
    )
    root = str(tmp_path.resolve())

    assert command[:4] == [
        "bwrap",
        "--die-with-parent",
        "--new-session",
        "--unshare-all",
    ]
    assert ["--proc", "/proc"] == command[
        command.index("--proc") : command.index("--proc") + 2
    ]
    assert ["--dev", "/dev"] == command[
        command.index("--dev") : command.index("--dev") + 2
    ]
    assert ["--tmpfs", "/tmp"] == command[
        command.index("--tmpfs") : command.index("--tmpfs") + 2
    ]
    assert ["--bind", root, "/workspace"] == command[
        command.index("--bind") : command.index("--bind") + 3
    ]
    assert ["--chdir", "/workspace"] == command[
        command.index("--chdir") : command.index("--chdir") + 2
    ]
    assert "--share-net" not in command
    assert command[-2:] == ["python3", "-V"]


def test_linux_bwrap_command_rejoins_network_only_when_enabled(tmp_path):
    command = _linux_bwrap_command(
        root_dir=tmp_path,
        argv=["echo", "ok"],
        allow_network=True,
    )

    assert "--unshare-all" in command
    assert command[-3:] == ["--share-net", "echo", "ok"]


def test_darwin_profile_scopes_file_content_reads(tmp_path):
    profile = _darwin_profile(tmp_path, allow_network=False)
    root = tmp_path.resolve()

    assert "(allow file-read*)" not in profile
    assert '(allow file-read-metadata (subpath "/"))' in profile
    assert f'(allow file-read-data (subpath "{root}"))' in profile


def test_darwin_profile_allows_active_python_runtime(tmp_path):
    profile = _darwin_profile(tmp_path, allow_network=False)

    for runtime_root in {Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve()}:
        if str(runtime_root) != "/":
            assert f'(allow file-read-data (subpath "{runtime_root}"))' in profile


def test_darwin_profile_escapes_workspace_path(tmp_path):
    root = tmp_path / 'quoted"root'
    profile = _darwin_profile(root, allow_network=False)
    escaped = str(root.resolve()).replace("\\", "\\\\").replace('"', '\\"')

    assert f'(allow file-read-data (subpath "{escaped}"))' in profile
    assert f'(allow file-write* (subpath "{escaped}"))' in profile


@pytest.mark.skipif(
    platform.system() != "Darwin" or shutil.which("sandbox-exec") is None,
    reason="requires macOS sandbox-exec",
)
def test_darwin_sandbox_cannot_read_outside_workspace(tmp_path):
    inside = tmp_path / "inside.txt"
    inside.write_text("workspace-only", encoding="utf-8")
    (tmp_path / "host-link").symlink_to("/etc/hosts")
    profile = _darwin_profile(tmp_path, allow_network=False)
    script = (
        "from pathlib import Path; "
        "print(Path('inside.txt').read_text()); "
        "\ntry: Path('/etc/hosts').read_text(); print('host-readable')\n"
        "except OSError: print('host-denied')\n"
        "try: Path('host-link').read_text(); print('link-readable')\n"
        "except OSError: print('link-denied')"
    )

    result = subprocess.run(
        ["sandbox-exec", "-p", profile, sys.executable, "-c", script],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "workspace-only" in result.stdout
    assert "host-denied" in result.stdout
    assert "host-readable" not in result.stdout
    assert "link-denied" in result.stdout
    assert "link-readable" not in result.stdout
