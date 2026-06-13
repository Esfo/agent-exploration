"""Sandboxed execution layer (spec section 16).

Prototype 2 ships a subprocess backend (option A): runs in the agent's work
directory with rlimit-based CPU/memory/file-size caps and output truncation.
It is NOT a security boundary the way a container is — a determined command can
still touch the host filesystem. The Docker backend (same Executor interface)
lands next and becomes a drop-in swap via select_executor().
"""
from __future__ import annotations

import shutil

from .executor import ExecResult, Executor
from .subprocess_backend import SubprocessExecutor


def docker_available() -> bool:
    return shutil.which("docker") is not None


def select_executor(settings) -> Executor:
    backend = (settings.get("SANDBOX_BACKEND", "subprocess") or "").lower()
    if backend == "docker" and docker_available():
        # Docker backend not implemented yet; fall through to subprocess with a note.
        # (Prototype 2A.) Returns subprocess so execution works today.
        pass
    return SubprocessExecutor(settings)


__all__ = ["ExecResult", "Executor", "SubprocessExecutor", "select_executor", "docker_available"]
