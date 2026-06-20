"""Docker execution backend.

Runs python/shell inside a hardened container:
    --network none (default), --memory, --cpus, --pids-limit,
    --read-only root + tmpfs, --cap-drop ALL, --security-opt no-new-privileges,
    the agent work dir mounted read/write at /agent (workdir).

By default a **persistent** container is kept warm per agent work directory and
reused via ``docker exec`` (set up once, torn down at shutdown), so we don't pay
container-startup cost on every run. Set ``SANDBOX_REUSE_CONTAINER=false`` to
fall back to a throwaway ``docker run --rm`` per execution.

Same Executor interface as the subprocess backend, so select_executor() swaps it
in transparently when SANDBOX_BACKEND=docker and docker is installed.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import time
from pathlib import Path

from .. import ids
from .executor import MAX_OUTPUT_KB, ExecResult, Executor

DEFAULT_IMAGE = "recursive-local-swarm-sandbox:latest"


class DockerExecutor(Executor):
    backend = "docker"

    def __init__(self, settings):
        self.s = settings
        self.image = settings.get("SANDBOX_IMAGE", DEFAULT_IMAGE) or DEFAULT_IMAGE
        self.memory_mb = settings.get_int("SANDBOX_MEMORY_MB", 2048) or 2048
        self.cpus = settings.get_float("SANDBOX_CPUS", 2.0) or 2.0
        self.pids = settings.get_int("SANDBOX_PIDS_LIMIT", 256) or 256
        self.network = settings.get("SANDBOX_NETWORK_DEFAULT", "none") or "none"
        self.reuse = settings.get_bool("SANDBOX_REUSE_CONTAINER", True)
        self._containers: dict[str, str] = {}   # work_dir -> container name

    # ----- hardening flags shared by run and the persistent daemon -----
    def _hardening(self) -> list[str]:
        argv = [
            "--network", self.network,
            "--memory", f"{self.memory_mb}m",
            "--memory-swap", f"{self.memory_mb}m",
            "--cpus", str(self.cpus),
            "--pids-limit", str(self.pids),
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
        ]
        if self.s.get_bool("SANDBOX_READ_ONLY_ROOT", True):
            argv += ["--read-only", "--tmpfs", "/tmp:rw,size=64m"]
        return argv

    def _mount(self, work_dir: Path) -> list[str]:
        return ["-v", f"{Path(work_dir).resolve()}:/agent:rw", "-w", "/agent",
                "-e", "HOME=/agent", "-e", "PYTHONPATH=/agent", "-e", "PYTHONUNBUFFERED=1"]

    # ----- throwaway run (fallback / reuse=false) -----
    def build_run_argv(self, work_dir: Path, inner: list[str]) -> list[str]:
        return (["docker", "run", "--rm"] + self._hardening() + self._mount(work_dir)
                + [self.image] + inner)

    # ----- persistent container (default) -----
    def build_daemon_argv(self, work_dir: Path, name: str) -> list[str]:
        return (["docker", "run", "-d", "--rm", "--name", name] + self._hardening()
                + self._mount(work_dir) + [self.image, "sleep", "infinity"])

    def build_exec_argv(self, name: str, inner: list[str]) -> list[str]:
        return ["docker", "exec", "-w", "/agent", name] + inner

    def _alive(self, name: str) -> bool:
        try:
            out = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", name],
                                 capture_output=True, text=True, timeout=10)
            return out.returncode == 0 and out.stdout.strip() == "true"
        except Exception:  # noqa: BLE001
            return False

    def _ensure_container(self, work_dir: Path) -> str | None:
        key = str(Path(work_dir).resolve())
        name = self._containers.get(key)
        if name and self._alive(name):
            return name
        name = "rls_" + ids.next_id("sbx")
        try:
            subprocess.run(self.build_daemon_argv(work_dir, name),
                           capture_output=True, timeout=60, check=True)
        except Exception:  # noqa: BLE001 - fall back to throwaway runs
            return None
        self._containers[key] = name
        return name

    def shutdown(self) -> None:
        for name in list(self._containers.values()):
            try:
                subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=15)
            except Exception:  # noqa: BLE001
                pass
        self._containers.clear()

    # ----- execution -----
    def _truncate(self, text: str) -> tuple[str, bool]:
        limit = MAX_OUTPUT_KB * 1024
        if len(text) <= limit:
            return text, False
        return text[:limit] + f"\n...[truncated, {len(text)-limit} more bytes]", True

    def _run(self, argv: list[str], work_dir: Path, timeout: int) -> ExecResult:
        cwd_before = str(Path(work_dir).resolve())
        start = time.monotonic()
        timed_out = False
        try:
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout + 5)
            exit_code, out, err = proc.returncode, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired as e:
            timed_out, exit_code = True, None
            out = (e.stdout or "") if isinstance(e.stdout, str) else (e.stdout or b"").decode("utf-8", "replace")
            err = ((e.stderr or "") if isinstance(e.stderr, str) else (e.stderr or b"").decode("utf-8", "replace")) \
                + f"\n[timed out after {timeout}s]"
        except FileNotFoundError:
            return ExecResult(exit_code=None, stdout="", stderr="docker not found",
                              duration_ms=0, sandbox_id=ids.next_id("sandbox"), backend=self.backend)
        duration_ms = int((time.monotonic() - start) * 1000)
        out, t1 = self._truncate(out or "")
        err, t2 = self._truncate(err or "")
        return ExecResult(
            exit_code=exit_code, stdout=out, stderr=err, duration_ms=duration_ms,
            timed_out=timed_out, truncated=t1 or t2,
            cwd_before=cwd_before, cwd_after=cwd_before, cwd_guard_passed=True,
            sandbox_id=ids.next_id("sandbox"), backend=self.backend,
        )

    def _argv_for(self, work_dir: Path, inner: list[str]) -> list[str]:
        """Reuse a warm container when enabled; otherwise a throwaway run."""
        if self.reuse:
            name = self._ensure_container(work_dir)
            if name:
                return self.build_exec_argv(name, inner)
        return self.build_run_argv(work_dir, inner)

    def run_python(self, code: str, work_dir: Path, timeout: int) -> ExecResult:
        runtime_dir = Path(work_dir) / ".runtime"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        fd, script = tempfile.mkstemp(suffix=".py", dir=str(runtime_dir))
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(code)
        rel = Path(script).name
        argv = self._argv_for(work_dir, ["python", f"/agent/.runtime/{rel}"])
        try:
            return self._run(argv, work_dir, timeout)
        finally:
            try:
                os.unlink(script)
            except OSError:
                pass

    def run_shell(self, command: str, work_dir: Path, timeout: int) -> ExecResult:
        argv = self._argv_for(work_dir, ["sh", "-c", command])
        return self._run(argv, work_dir, timeout)
