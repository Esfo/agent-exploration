"""profile tool (spec section 25).

Runs a workload through the sandbox executor and records a baseline runtime.
For python workloads it wraps the command in cProfile and extracts the top
time-consuming functions. Artifacts go to the agent's profiling dir and a row
to profiling_reports.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .. import ids
from ..runtime_guards.command_guard import check_command

_PY_PREFIX = re.compile(r"^\s*python3?\b")


def _parse_cprofile_top(stdout: str, n: int = 6) -> list[str]:
    lines = stdout.splitlines()
    out: list[str] = []
    started = False
    for ln in lines:
        if "ncalls" in ln and "tottime" in ln:
            started = True
            continue
        if started:
            if ln.strip():
                out.append(ln.strip())
            if len(out) >= n:
                break
    return out


def execute(ctx, agent_id: str, args: dict) -> dict:
    if not ctx.settings.get_bool("PROFILING_ENABLED", True):
        return {"status": "error", "failure": "permission_denied", "detail": "profiling disabled"}
    agent = ctx.db.get_agent(agent_id)
    command = args.get("command", "")
    target = args.get("target", "workload")
    if not command.strip():
        return {"status": "error", "failure": "invalid_tool_args", "detail": "missing 'command'"}

    guard = check_command(command, args,
                          network_enabled=ctx.settings.get_bool("SHELL_NETWORK_ENABLED", False))
    if not guard.allowed:
        return {"status": "blocked", "failure": "command_guard_blocked",
                "reasons": guard.reasons, "missing_fields": guard.missing_fields}

    language = args.get("language", "python")
    run_cmd = command
    cprofile = False
    if language == "python" and _PY_PREFIX.match(command) and "cProfile" not in command:
        run_cmd = _PY_PREFIX.sub("python -m cProfile -s tottime", command, count=1)
        cprofile = True

    timeout = min(int(args.get("timeout_seconds", 120)),
                  ctx.settings.get_int("SHELL_MAX_TIMEOUT_SECONDS", 300) or 300)
    res = ctx.executor.run_shell(run_cmd, Path(agent["assigned_directory"]), timeout)

    top = _parse_cprofile_top(res.stdout) if cprofile else []
    baseline_ms = res.duration_ms

    prof_dir = Path(agent["assigned_directory"]).parent / "profiling"
    prof_dir.mkdir(parents=True, exist_ok=True)
    (prof_dir / "profile_summary.txt").write_text(res.stdout[-20000:], encoding="utf-8")
    (prof_dir / "timing.json").write_text(
        json.dumps({"target": target, "baseline_runtime_ms": baseline_ms,
                    "exit_code": res.exit_code, "command": run_cmd}, indent=2),
        encoding="utf-8")

    report_id = ids.next_id("profile")
    report = {"target": target, "baseline_runtime_ms": baseline_ms,
              "top_bottlenecks": top, "command": run_cmd, "exit_code": res.exit_code}
    ctx.db.conn.execute(
        "INSERT INTO profiling_reports (id, agent_id, target, baseline_runtime_ms, report_json, created_at)"
        " VALUES (?,?,?,?,?,datetime('now'))",
        (report_id, agent_id, target, baseline_ms, json.dumps(report)),
    )
    ctx.db.conn.commit()

    return {"status": "ok" if res.exit_code == 0 else "command_failed",
            "profiling_report_id": report_id, "baseline_runtime_ms": baseline_ms,
            "top_bottlenecks": top, "exit_code": res.exit_code,
            "stderr": res.stderr[-2000:]}
