"""Docker execution backend (spec section 16).

Runs python/shell inside a throwaway container with real isolation:
    --network none (default), --memory, --cpus, --pids-limit,
    --read-only root + tmpfs, --cap-drop ALL, --security-opt no-new-privileges,
    the agent work dir mounted read/write at /agent (workdir), supporting mounts
    read-only.

Same Executor interface as the subprocess backend, so select_executor() swaps
it in transparently when SANDBOX_BACKEND=docker and docker is installed.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import time
from pathlib import Path

from .. import ids
from .executor import MAX_OUTPUT_KB, ExecResult, Executor

DEFAULT_IMAGE = "python:3.12-slim"


class DockerExecutor(Executor):
    backend = "docker"

    def __init__(self, settings):
        self.s = settings
        self.image = settings.get("SANDBOX_IMAGE", DEFAULT_IMAGE) or DEFAULT_IMAGE
        self.memory_mb = settings.get_int("SANDBOX_MEMORY_MB", 2048) or 2048
        self.cpus = settings.get_float("SANDBOX_CPUS", 2.0) or 2.0
        self.pids = settings.get_int("SANDBOX_PIDS_LIMIT", 256) or 256
        self.network = settings.get("SANDBOX_NETWORK_DEFAULT", "none") or "none"

    # ----- argv construction (unit-tested without Docker present) -----
    def build_run_argv(self, work_dir: Path, inner: list[str], *,
                       extra_mounts: list[tuple[str, str, str]] | None = None) -> list[str]:
        work_dir = Path(work_dir).resolve()
        argv = [
            "docker", "run", "--rm",
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
        # Agent work dir is the only writable mount + working directory.
        argv += ["-v", f"{work_dir}:/agent:rw", "-w", "/agent",
                 "-e", "HOME=/agent", "-e", "PYTHONPATH=/agent",
                 "-e", "PYTHONUNBUFFERED=1"]
        for host, dest, mode in (extra_mounts or self._default_mounts(work_dir)):
            if Path(host).exists():
                argv += ["-v", f"{host}:{dest}:{mode}"]
        argv.append(self.image)
        argv += inner
        return argv

    def _default_mounts(self, work_dir: Path) -> list[tuple[str, str, str]]:
        # The agent work dir is the only writable mount; nothing else is exposed.
        return []

    # ----- execution -----
    def _truncate(self, text: str, kind: str) -> tuple[str, bool]:
        limit = MAX_OUTPUT_KB * 1024
        if len(text) <= limit:
            return text, False
        return text[:limit] + f"\n...[truncated, {len(text)-limit} more bytes]", True

    def _run(self, argv: list[str], work_dir: Path, timeout: int, kind: str) -> ExecResult:
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
        out, t1 = self._truncate(out or "", kind)
        err, t2 = self._truncate(err or "", kind)
        return ExecResult(
            exit_code=exit_code, stdout=out, stderr=err, duration_ms=duration_ms,
            timed_out=timed_out, truncated=t1 or t2,
            cwd_before=cwd_before, cwd_after=cwd_before, cwd_guard_passed=True,
            sandbox_id=ids.next_id("sandbox"), backend=self.backend,
        )

    def run_python(self, code: str, work_dir: Path, timeout: int) -> ExecResult:
        runtime_dir = Path(work_dir) / ".runtime"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        fd, script = tempfile.mkstemp(suffix=".py", dir=str(runtime_dir))
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(code)
        rel = Path(script).name
        argv = self.build_run_argv(work_dir, ["python", f"/agent/.runtime/{rel}"])
        try:
            return self._run(argv, work_dir, timeout, "python")
        finally:
            try:
                os.unlink(script)
            except OSError:
                pass

    def run_shell(self, command: str, work_dir: Path, timeout: int) -> ExecResult:
        argv = self.build_run_argv(work_dir, ["sh", "-c", command])
        return self._run(argv, work_dir, timeout, "shell")
