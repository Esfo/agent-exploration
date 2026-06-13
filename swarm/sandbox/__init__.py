"""Sandboxed execution layer (spec section 16).

Prototype 2 ships a subprocess backend (option A): runs in the agent's work
directory with rlimit-based CPU/memory/file-size caps and output truncation.
It is NOT a security boundary the way a container is — a determined command can
still touch the host filesystem. The Docker backend (same Executor interface)
lands next and becomes a drop-in swap via select_executor().
"""
from __future__ import annotations

import shutil

from .docker_backend import DockerExecutor
from .executor import ExecResult, Executor
from .subprocess_backend import SubprocessExecutor


def docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        import subprocess
        subprocess.run(["docker", "info"], capture_output=True, timeout=10, check=True)
        return True
    except Exception:  # noqa: BLE001 - docker present but daemon down
        return False


def select_executor(settings) -> Executor:
    """Docker when requested and usable; otherwise subprocess fallback.

    SANDBOX_BACKEND=docker uses real container isolation. If the daemon isn't
    reachable, falls back to subprocess so the runtime still works (with the
    weaker isolation caveat).
    """
    backend = (settings.get("SANDBOX_BACKEND", "subprocess") or "").lower()
    if backend == "docker" and docker_available():
        return DockerExecutor(settings)
    return SubprocessExecutor(settings)


__all__ = ["ExecResult", "Executor", "SubprocessExecutor", "DockerExecutor",
           "select_executor", "docker_available"]
