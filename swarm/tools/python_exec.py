"""python execution tool (spec section 22). Sandboxed via ctx.executor."""
from __future__ import annotations

from pathlib import Path

from ..runtime_guards.command_guard import check_command


def execute(ctx, agent_id: str, args: dict) -> dict:
    if not ctx.settings.get_bool("PYTHON_EXECUTION_ENABLED", True):
        return {"status": "error", "failure": "permission_denied", "detail": "python disabled"}
    agent = ctx.db.get_agent(agent_id)
    code = args.get("code", "")
    if not code.strip():
        return {"status": "error", "failure": "invalid_tool_args", "detail": "missing 'code'"}

    # Command-questioning fields are required for code execution too.
    guard = check_command(
        "python", args,
        network_enabled=ctx.settings.get_bool("PYTHON_NETWORK_ENABLED", False),
    )
    if not guard.allowed:
        return {"status": "blocked", "failure": "command_guard_blocked",
                "reasons": guard.reasons, "missing_fields": guard.missing_fields}

    default_t = ctx.settings.get_int("PYTHON_DEFAULT_TIMEOUT_SECONDS", 30) or 30
    max_t = ctx.settings.get_int("PYTHON_MAX_TIMEOUT_SECONDS", 300) or 300
    timeout = min(int(args.get("timeout_seconds", default_t)), max_t)

    res = ctx.executor.run_python(code, Path(agent["assigned_directory"]), timeout)
    ctx.db.conn.execute(
        "INSERT INTO sandboxes (id, agent_id, backend, status, network_mode, created_at)"
        " VALUES (?,?,?,?,?,datetime('now'))",
        (res.sandbox_id, agent_id, res.backend, "closed", "none"),
    )
    ctx.db.conn.commit()
    return {"status": "ok" if res.exit_code == 0 else "command_failed", **res.to_dict()}
