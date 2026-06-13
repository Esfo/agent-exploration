"""shell execution tool (spec section 23). Sandboxed via ctx.executor."""
from __future__ import annotations

from pathlib import Path

from ..runtime_guards.command_guard import check_command


def execute(ctx, agent_id: str, args: dict) -> dict:
    if not ctx.settings.get_bool("SHELL_EXECUTION_ENABLED", True):
        return {"status": "error", "failure": "permission_denied", "detail": "shell disabled"}
    agent = ctx.db.get_agent(agent_id)
    command = args.get("command", "")
    if not command.strip():
        return {"status": "error", "failure": "invalid_tool_args", "detail": "missing 'command'"}

    guard = check_command(
        command, args,
        network_enabled=ctx.settings.get_bool("SHELL_NETWORK_ENABLED", False),
    )
    if not guard.allowed:
        return {"status": "blocked", "failure": "command_guard_blocked",
                "reasons": guard.reasons, "missing_fields": guard.missing_fields}

    default_t = ctx.settings.get_int("SHELL_DEFAULT_TIMEOUT_SECONDS", 30) or 30
    max_t = ctx.settings.get_int("SHELL_MAX_TIMEOUT_SECONDS", 300) or 300
    timeout = min(int(args.get("timeout_seconds", default_t)), max_t)

    res = ctx.executor.run_shell(command, Path(agent["assigned_directory"]), timeout)
    ctx.db.conn.execute(
        "INSERT INTO sandboxes (id, agent_id, backend, status, network_mode, created_at)"
        " VALUES (?,?,?,?,?,datetime('now'))",
        (res.sandbox_id, agent_id, res.backend, "closed", "none"),
    )
    ctx.db.conn.commit()
    return {"status": "ok" if res.exit_code == 0 else "command_failed", **res.to_dict()}
