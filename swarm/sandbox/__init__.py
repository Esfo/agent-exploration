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


class DisabledExecutor(Executor):
    """Refuses to run code. Used when the docker sandbox is required but
    unavailable, so we never silently run agent code on the host."""

    backend = "disabled"

    def __init__(self, reason: str):
        self.reason = reason

    def _blocked(self) -> ExecResult:
        return ExecResult(exit_code=None, stdout="",
                          stderr=f"sandbox unavailable: {self.reason}",
                          duration_ms=0, backend=self.backend)

    def run_python(self, code, work_dir, timeout):
        return self._blocked()

    def run_shell(self, command, work_dir, timeout):
        return self._blocked()


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
    """Pick the execution backend.

    SANDBOX_BACKEND=docker uses real container isolation. If Docker isn't
    available and SANDBOX_REQUIRE_DOCKER is true (default), code execution is
    DISABLED rather than silently falling back to running on the host. Set
    SANDBOX_REQUIRE_DOCKER=false to explicitly allow the weaker subprocess
    backend (rlimits only — NOT host isolation).
    """
    backend = (settings.get("SANDBOX_BACKEND", "docker") or "").lower()
    if backend == "docker":
        if docker_available():
            return DockerExecutor(settings)
        if settings.get_bool("SANDBOX_REQUIRE_DOCKER", True):
            return DisabledExecutor("Docker is required but not reachable; "
                                    "set SANDBOX_REQUIRE_DOCKER=false to allow "
                                    "host execution (not isolated).")
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
        if settings.get_bool("SANDBOX_REQUIRE_DOCKER", True):
            msg = ("WARNING: SANDBOX_BACKEND=docker but Docker is not reachable. "
                   "Code execution is DISABLED (agents can't run code) so nothing "
                   "runs unsandboxed on your host. Start Docker, run "
                   "`python -m swarm.main --initiate`, or set "
                   "SANDBOX_REQUIRE_DOCKER=false to allow host execution.")
        else:
            msg = ("WARNING: Docker not reachable and SANDBOX_REQUIRE_DOCKER=false "
                   "— agent code will run on the HOST with rlimits only, which is "
                   "NOT isolation. Start Docker for a real sandbox.")
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
           "DisabledExecutor", "select_executor", "docker_available", "image_present",
           "docker_preflight", "build_image", "run_code", "format_result"]
