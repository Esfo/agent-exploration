"""Persistent sandboxed terminals (spec section 17).

A terminal is a stateful session with a tracked cwd (relative to the agent
jail root). Each terminal_command runs through the sandbox executor; the cwd is
enforced before and after every command by the cwd guard. When
RESET_CWD_AFTER_EVERY_COMMAND is set, the cwd returns to the jail root after
each command (the spec default), so a command cannot quietly wander off.
"""
from __future__ import annotations

import re
from pathlib import Path

from .. import ids
from ..runtime_guards import cwd_guard
from ..runtime_guards.command_guard import check_command

_MARK = re.compile(r"__CWD__(.*?)__END__", re.DOTALL)


def _jail_root(ctx, agent) -> str:
    """The cwd jail root for this agent, depending on the execution backend."""
    if getattr(ctx.executor, "backend", "subprocess") == "docker":
        return "/agent"
    return str(Path(agent["assigned_directory"]).resolve())


def open_terminal(ctx, agent_id: str, args: dict) -> dict:
    agent = ctx.db.get_agent(agent_id)
    if agent is None:
        return {"status": "error", "failure": "permission_denied", "detail": "no such agent"}
    term_id = ids.next_id("terminal")
    sandbox_id = ids.next_id("sandbox")
    ctx.db.conn.execute(
        "INSERT INTO terminals (id, agent_id, sandbox_id, terminal_type, assigned_root,"
        " current_cwd, status, created_at) VALUES (?,?,?,?,?,?,?,datetime('now'))",
        (term_id, agent_id, sandbox_id, args.get("terminal_type", "shell"),
         _jail_root(ctx, agent), ".", "active"),
    )
    ctx.db.conn.commit()
    ctx.events._jsonl("terminals.jsonl", {"event": "terminal_opened",
                      "agent_id": agent_id, "terminal_id": term_id, "sandbox_id": sandbox_id})
    return {"status": "ok", "terminal_id": term_id, "sandbox_id": sandbox_id, "cwd": "."}


def close_terminal(ctx, agent_id: str, args: dict) -> dict:
    term_id = args.get("terminal_id", "")
    ctx.db.conn.execute(
        "UPDATE terminals SET status='closed', closed_at=datetime('now') WHERE id=? AND agent_id=?",
        (term_id, agent_id),
    )
    ctx.db.conn.commit()
    return {"status": "ok", "closed": term_id}


def terminal_command(ctx, agent_id: str, args: dict) -> dict:
    term_id = args.get("terminal_id", "")
    term = ctx.db.conn.execute(
        "SELECT * FROM terminals WHERE id=? AND agent_id=?", (term_id, agent_id)
    ).fetchone()
    if term is None:
        return {"status": "error", "failure": "terminal_create_failed",
                "detail": f"no open terminal {term_id!r}; open_terminal first"}
    if term["status"] != "active":
        return {"status": "error", "failure": "terminal_create_failed", "detail": "terminal closed"}

    command = args.get("command", "")
    if not command.strip():
        return {"status": "error", "failure": "invalid_tool_args", "detail": "missing 'command'"}

    guard = check_command(command, args,
                          network_enabled=ctx.settings.get_bool("SHELL_NETWORK_ENABLED", False))
    if not guard.allowed:
        return {"status": "blocked", "failure": "command_guard_blocked",
                "reasons": guard.reasons, "missing_fields": guard.missing_fields}

    agent = ctx.db.get_agent(agent_id)
    root = term["assigned_root"]
    cwd_before = term["current_cwd"] or "."

    # Compose: start in the tracked cwd, run the command, then emit pwd marker.
    start = "." if cwd_before in ("", ".") else f"./{cwd_before}"
    composed = (f'cd "{start}" 2>/dev/null || cd .; '
                f'{{ {command}; }}; __rc=$?; printf "__CWD__%s__END__" "$(pwd)"; exit $__rc')

    default_t = ctx.settings.get_int("SHELL_DEFAULT_TIMEOUT_SECONDS", 30) or 30
    max_t = ctx.settings.get_int("SHELL_MAX_TIMEOUT_SECONDS", 300) or 300
    timeout = min(int(args.get("timeout_seconds", default_t)), max_t)

    res = ctx.executor.run_shell(composed, Path(agent["assigned_directory"]), timeout)

    # Extract reported pwd and strip the marker from visible output.
    m = _MARK.search(res.stdout)
    reported_pwd = m.group(1).strip() if m else root
    visible_stdout = _MARK.sub("", res.stdout).rstrip()

    new_rel = cwd_guard.relative(reported_pwd, root)
    cwd_guard_passed = new_rel is not None
    if not cwd_guard_passed:
        new_rel = "."  # command left the jail; reset

    reset = ctx.settings.get_bool("RESET_CWD_AFTER_EVERY_COMMAND", True)
    final_cwd = "." if reset else new_rel
    ctx.db.conn.execute(
        "UPDATE terminals SET current_cwd=? WHERE id=?", (final_cwd, term_id)
    )
    ctx.db.conn.execute(
        "INSERT INTO terminal_commands (terminal_id, sandbox_id, agent_id, command, reason,"
        " expected_result, destructive_risk_answer, cwd_before, cwd_after, cwd_guard_passed,"
        " exit_code, duration_ms, created_at, finished_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'),datetime('now'))",
        (term_id, res.sandbox_id, agent_id, command, args.get("reason", ""),
         args.get("expected_result", ""), args.get("destructive_risk_answer", ""),
         cwd_before, new_rel, 1 if cwd_guard_passed else 0,
         res.exit_code, res.duration_ms),
    )
    ctx.db.conn.commit()

    status = "ok" if (res.exit_code == 0 and cwd_guard_passed) else "command_failed"
    return {
        "status": status,
        "exit_code": res.exit_code,
        "stdout": visible_stdout,
        "stderr": res.stderr,
        "duration_ms": res.duration_ms,
        "timed_out": res.timed_out,
        "cwd_before": cwd_before,
        "cwd_after": new_rel,
        "cwd_guard_passed": cwd_guard_passed,
        "terminal_id": term_id,
        "sandbox_id": res.sandbox_id,
    }
