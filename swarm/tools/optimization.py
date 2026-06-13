"""optimize tool (spec section 26).

Brackets an optimization: the agent makes the code change via write_file; this
tool runs the validation command (in the sandbox), measures the after-runtime,
compares to the before-runtime (explicit or from a profiling report), and
records an optimization report. Optimization requires a prior profiling target
when OPTIMIZATION_REQUIRES_PROFILING_FIRST is set.
"""
from __future__ import annotations

import json
from pathlib import Path

from .. import ids
from ..runtime_guards.command_guard import check_command


def execute(ctx, agent_id: str, args: dict) -> dict:
    if not ctx.settings.get_bool("OPTIMIZATION_ENABLED", True):
        return {"status": "error", "failure": "permission_denied", "detail": "optimization disabled"}
    agent = ctx.db.get_agent(agent_id)
    target = args.get("target", "workload")

    before_ms = args.get("before_runtime_ms")
    report_id = args.get("profiling_report_id")
    if before_ms is None and report_id:
        row = ctx.db.conn.execute(
            "SELECT baseline_runtime_ms FROM profiling_reports WHERE id=?", (report_id,)
        ).fetchone()
        if row:
            before_ms = row["baseline_runtime_ms"]

    if ctx.settings.get_bool("OPTIMIZATION_REQUIRES_PROFILING_FIRST", True) and before_ms is None:
        return {"status": "blocked", "failure": "optimization_failed",
                "detail": "no profiling baseline; run profile first or pass before_runtime_ms"}

    validation_command = args.get("validation_command", "")
    after_ms = None
    validation = "not_run"
    if validation_command.strip():
        guard = check_command(validation_command, args)
        if not guard.allowed:
            return {"status": "blocked", "failure": "command_guard_blocked",
                    "reasons": guard.reasons, "missing_fields": guard.missing_fields}
        timeout = int(args.get("timeout_seconds", 120))
        res = ctx.executor.run_shell(validation_command, Path(agent["assigned_directory"]), timeout)
        after_ms = res.duration_ms
        validation = "passed" if res.exit_code == 0 else "failed"

    improvement = None
    if before_ms and after_ms is not None and before_ms > 0:
        improvement = f"{(before_ms - after_ms) / before_ms * 100:.1f}%"

    report_id_out = ids.next_id("optimize")
    report = {"target": target, "change_summary": args.get("change_summary", args.get("goal", "")),
              "before_runtime_ms": before_ms, "after_runtime_ms": after_ms,
              "improvement": improvement, "validation": validation,
              "remaining_risks": args.get("remaining_risks", [])}
    ctx.db.conn.execute(
        "INSERT INTO optimization_reports (id, agent_id, target, before_runtime_ms, after_runtime_ms,"
        " improvement, report_json, created_at) VALUES (?,?,?,?,?,?,?,datetime('now'))",
        (report_id_out, agent_id, target, before_ms, after_ms, improvement, json.dumps(report)),
    )
    ctx.db.conn.commit()

    opt_dir = Path(agent["assigned_directory"]).parent / "optimization"
    opt_dir.mkdir(parents=True, exist_ok=True)
    (opt_dir / f"{report_id_out}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    status = "ok"
    if validation == "failed":
        status = "command_failed"
    return {"status": status, "optimization_report_id": report_id_out, **report}
