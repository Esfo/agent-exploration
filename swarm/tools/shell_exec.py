"""shell execution tool (spec section 23). Sandboxed via ctx.executor."""
from __future__ import annotations

from pathlib import Path

from ..runtime_guards.command_guard import check_command
from ..sandbox.executor import DEFAULT_EXEC_TIMEOUT


def execute(ctx, agent_id: str, args: dict) -> dict:
    agent = ctx.db.get_agent(agent_id)
    command = args.get("command", "")
    if not command.strip():
        return {"status": "error", "failure": "invalid_tool_args", "detail": "missing 'command'"}

    guard = check_command(command, args)
    if not guard.allowed:
        return {"status": "blocked", "failure": "command_guard_blocked",
                "reasons": guard.reasons, "missing_fields": guard.missing_fields}

    timeout = int(args.get("timeout_seconds", DEFAULT_EXEC_TIMEOUT))

    res = ctx.executor.run_shell(command, Path(agent["assigned_directory"]), timeout)
    ctx.db.conn.execute(
        "INSERT INTO sandboxes (id, agent_id, backend, status, network_mode, created_at)"
        " VALUES (?,?,?,?,?,datetime('now'))",
        (res.sandbox_id, agent_id, res.backend, "closed", "none"),
    )
    ctx.db.conn.commit()
    return {"status": "ok" if res.exit_code == 0 else "command_failed", **res.to_dict()}
