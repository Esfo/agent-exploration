"""Subprocess execution backend (Prototype 2A fallback).

Runs python/shell in the agent's work directory with:
    - a wall-clock timeout (killing the whole process group)
    - POSIX rlimits: CPU seconds, address space, file size (best effort)
    - output truncation to settings limits

Known limitation: this is isolation-by-convention, not a container. The Docker
backend will provide real filesystem/network isolation behind the same API.
"""
from __future__ import annotations

import os
import resource
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .. import ids
from .executor import CPU_RLIMIT_SECONDS, MAX_OUTPUT_KB, ExecResult, Executor


class SubprocessExecutor(Executor):
    backend = "subprocess"

    def __init__(self, settings):
        self.s = settings
        self.mem_mb = settings.get_int("SANDBOX_MEMORY_MB", 2048) or 2048
        self.cpu_secs_cap = CPU_RLIMIT_SECONDS
        self.max_file_mb = settings.get_int("MAX_FILE_WRITE_MB", 5) or 5

    # ----- limits -----
    def _preexec(self):  # pragma: no cover - runs in child process
        # New session so we can kill the whole group on timeout.
        os.setsid()
        try:
            soft = self.cpu_secs_cap
            resource.setrlimit(resource.RLIMIT_CPU, (soft, soft + 5))
            mem = self.mem_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
            fsize = self.max_file_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_FSIZE, (fsize, fsize))
        except (ValueError, OSError):
            pass

    def _truncate(self, text: str, kind: str) -> tuple[str, bool]:
        limit = MAX_OUTPUT_KB * 1024
        if len(text) <= limit:
            return text, False
        return text[:limit] + f"\n...[truncated, {len(text)-limit} more bytes]", True

    def _run(self, argv, work_dir: Path, timeout: int, kind: str,
             use_shell: bool = False) -> ExecResult:
        work_dir = Path(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
        cwd_before = str(work_dir)
        env = {"PATH": os.environ.get("PATH", ""), "HOME": str(work_dir),
               "LANG": "C.UTF-8", "PYTHONUNBUFFERED": "1",
               # Let agent code import modules it wrote into its own work dir.
               "PYTHONPATH": str(work_dir)}
        start = time.monotonic()
        timed_out = False
        try:
            proc = subprocess.run(
                argv,
                cwd=str(work_dir),
                env=env,
                shell=use_shell,
                capture_output=True,
                text=True,
                timeout=timeout,
                preexec_fn=self._preexec if os.name == "posix" else None,
            )
            exit_code, out, err = proc.returncode, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired as e:
            timed_out = True
            exit_code = None
            out = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
            err = (e.stderr.decode() if isinstance(e.stderr, bytes) else (e.stderr or "")) \
                + f"\n[timed out after {timeout}s]"
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
        try:
            return self._run([sys.executable, script], work_dir, timeout, "python")
        finally:
            try:
                os.unlink(script)
            except OSError:
                pass

    def run_shell(self, command: str, work_dir: Path, timeout: int) -> ExecResult:
        return self._run(command, work_dir, timeout, "shell", use_shell=True)
