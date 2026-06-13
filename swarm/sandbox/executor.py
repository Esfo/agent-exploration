"""Executor interface + result type (spec sections 16, 22, 23)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# Code-level execution defaults (NOT user settings). The agent supplies the
# timeout in its tool call; this is only the fallback when it omits one.
DEFAULT_EXEC_TIMEOUT = 60
MAX_OUTPUT_KB = 512
# Generous CPU-time rlimit ceiling so a runaway sandbox can't peg a core forever;
# this is a safety stop, not a user-facing limit.
CPU_RLIMIT_SECONDS = 1800


@dataclass
class ExecResult:
    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False
    truncated: bool = False
    cwd_before: str = ""
    cwd_after: str = ""
    cwd_guard_passed: bool = True
    sandbox_id: str = ""
    backend: str = "subprocess"

    def to_dict(self) -> dict:
        return {
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration_ms": self.duration_ms,
            "timed_out": self.timed_out,
            "truncated": self.truncated,
            "cwd_before": self.cwd_before,
            "cwd_after": self.cwd_after,
            "cwd_guard_passed": self.cwd_guard_passed,
            "sandbox_id": self.sandbox_id,
            "backend": self.backend,
        }


class Executor:
    """Abstract execution backend. Implementations run code confined to work_dir."""

    backend = "abstract"

    def run_python(self, code: str, work_dir: Path, timeout: int) -> ExecResult:
        raise NotImplementedError

    def run_shell(self, command: str, work_dir: Path, timeout: int) -> ExecResult:
        raise NotImplementedError
