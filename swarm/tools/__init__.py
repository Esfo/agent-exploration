"""Tool registry and execution dispatch (spec section 20).

Prototype 1 implements: spawn_agents, report_progress, finish. Each tool is a
callable taking (ctx, agent_id, args) and returning a result dict. ctx is the
RuntimeContext that carries db, settings, event bus, selector, etc.
"""
from __future__ import annotations

from . import finish as _finish
from . import progress as _progress
from . import spawn_agents as _spawn

# name -> (handler, terminal?) where terminal means "agent loop should stop after".
REGISTRY = {
    "finish": (_finish.execute, True),
    "report_progress": (_progress.execute, False),
    "spawn_agents": (_spawn.execute, True),
}


def execute(ctx, agent_id: str, name: str, args: dict) -> tuple[dict, bool]:
    entry = REGISTRY.get(name)
    if entry is None:
        return ({"status": "error", "failure": "unknown_tool", "tool": name}, False)
    handler, terminal = entry
    try:
        result = handler(ctx, agent_id, args)
    except Exception as e:  # noqa: BLE001 - surface failure to the agent, don't crash runtime
        return ({"status": "error", "failure": "tool_exception", "detail": str(e)}, False)
    return result, terminal
