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
from .image import build_image
from .runner import format_result, run_code
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


def image_present(image: str) -> bool:
    try:
        import subprocess
        subprocess.run(["docker", "image", "inspect", image],
                       capture_output=True, timeout=15, check=True)
        return True
    except Exception:  # noqa: BLE001
        return False


def docker_preflight(settings, events=None) -> str:
    """Check the sandbox image is available; pull it once if missing.

    Non-fatal: logs guidance and returns a status string. Only acts when the
    docker backend is selected and the daemon is reachable.
    """
    backend = (settings.get("SANDBOX_BACKEND", "subprocess") or "").lower()
    if backend != "docker":
        return "skipped (backend != docker)"
    if not docker_available():
        msg = ("SANDBOX_BACKEND=docker but the Docker daemon is not reachable; "
               "execution will fall back to the subprocess backend.")
        if events:
            events.chat(msg)
        return "daemon_unavailable"
    image = settings.get("SANDBOX_IMAGE", "python:3.12-slim") or "python:3.12-slim"
    if image_present(image):
        return "ready"
    if events:
        events.chat(f"Pulling sandbox image {image} (first run only)…")
    try:
        import subprocess
        subprocess.run(["docker", "pull", image], capture_output=True, timeout=600, check=True)
        return "pulled"
    except Exception as e:  # noqa: BLE001
        if events:
            events.chat(f"Could not pull {image}: {e}. Run `docker pull {image}` manually.")
        return "pull_failed"


__all__ = ["ExecResult", "Executor", "SubprocessExecutor", "DockerExecutor",
           "select_executor", "docker_available", "image_present", "docker_preflight",
           "build_image", "run_code", "format_result"]
