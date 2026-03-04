from __future__ import annotations

import platform
from dataclasses import dataclass
from pathlib import Path
from shutil import which


class SandboxUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class SandboxSelection:
    backend_id: str
    mode: str
    root_dir: Path
    allow_network: bool = False

    def wrap_command(self, argv: list[str]) -> list[str]:
        if self.backend_id == "unsafe_none":
            return argv
        if self.backend_id == "darwin_sandbox_exec":
            profile = _darwin_profile(self.root_dir, self.allow_network)
            return ["sandbox-exec", "-p", profile, *argv]
        if self.backend_id == "linux_bwrap":
            return _linux_bwrap_command(
                root_dir=self.root_dir,
                argv=argv,
                allow_network=self.allow_network,
            )
        return argv


def _darwin_profile(root_dir: Path, allow_network: bool) -> str:
    root = str(root_dir.resolve()).replace("\\", "\\\\").replace('"', '\\"')
    network_rule = "(allow network*)" if allow_network else "(deny network*)"
    # Keep defaults restricted, allow command execution, and constrain writes to the workspace.
    return (
        '(version 1)(deny default)(import "system.sb")'
        f"{network_rule}"
        "(allow process*)"
        "(allow file-read*)"
        f'(allow file-write* (subpath "{root}"))'
        '(allow file-write* (subpath "/tmp"))'
        '(allow file-write* (subpath "/private/tmp"))'
    )


def _linux_bwrap_command(
    *, root_dir: Path, argv: list[str], allow_network: bool
) -> list[str]:
    root = str(root_dir.resolve())
    cmd = [
        "bwrap",
        "--die-with-parent",
        "--new-session",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--bind",
        root,
        root,
        "--chdir",
        root,
    ]
    if allow_network:
        cmd.append("--share-net")
    cmd.extend(argv)
    return cmd


def resolve_sandbox(
    *,
    mode: str,
    root_dir: Path,
    require_sandbox: bool,
    allow_network: bool,
) -> SandboxSelection:
    normalized_mode = str(mode).strip().lower() or "hybrid_auto"
    system = platform.system().lower()

    if normalized_mode == "unsafe_none":
        return SandboxSelection(
            backend_id="unsafe_none",
            mode=normalized_mode,
            root_dir=root_dir,
            allow_network=allow_network,
        )

    if normalized_mode == "darwin_sandbox":
        if which("sandbox-exec"):
            return SandboxSelection(
                backend_id="darwin_sandbox_exec",
                mode=normalized_mode,
                root_dir=root_dir,
                allow_network=allow_network,
            )
        if require_sandbox:
            raise SandboxUnavailableError("sandbox-exec backend is unavailable")
        return SandboxSelection(
            backend_id="unsafe_none",
            mode=normalized_mode,
            root_dir=root_dir,
            allow_network=allow_network,
        )

    if normalized_mode == "linux_bwrap":
        if which("bwrap"):
            return SandboxSelection(
                backend_id="linux_bwrap",
                mode=normalized_mode,
                root_dir=root_dir,
                allow_network=allow_network,
            )
        if require_sandbox:
            raise SandboxUnavailableError("bwrap backend is unavailable")
        return SandboxSelection(
            backend_id="unsafe_none",
            mode=normalized_mode,
            root_dir=root_dir,
            allow_network=allow_network,
        )

    if system == "darwin" and which("sandbox-exec"):
        return SandboxSelection(
            backend_id="darwin_sandbox_exec",
            mode="hybrid_auto",
            root_dir=root_dir,
            allow_network=allow_network,
        )
    if system == "linux" and which("bwrap"):
        return SandboxSelection(
            backend_id="linux_bwrap",
            mode="hybrid_auto",
            root_dir=root_dir,
            allow_network=allow_network,
        )
    if require_sandbox:
        raise SandboxUnavailableError("no compatible sandbox backend detected")
    return SandboxSelection(
        backend_id="unsafe_none",
        mode="hybrid_auto",
        root_dir=root_dir,
        allow_network=allow_network,
    )

