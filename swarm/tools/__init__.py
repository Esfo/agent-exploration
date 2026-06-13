"""Tool registry and execution dispatch (spec section 20).

Prototype 1: spawn_agents, report_progress, finish.
Prototype 2: file tools (list/read/write/append/delete) + sandboxed python/shell.
Each handler takes (ctx, agent_id, args) and returns a result dict. ctx is the
RuntimeContext carrying db, settings, events, selector, executor, etc.
"""
from __future__ import annotations

from . import files as _files
from . import finish as _finish
from . import progress as _progress
from . import python_exec as _python
from . import reconcile as _reconcile
from . import shell_exec as _shell
from . import spawn_agents as _spawn
from . import terminals as _terminals
from . import web as _web

# name -> (handler, terminal?) where terminal means "stop the agent loop after".
REGISTRY = {
    "finish": (_finish.execute, True),
    "report_progress": (_progress.execute, False),
    "spawn_agents": (_spawn.execute, True),
    "list_files": (_files.list_files, False),
    "read_file": (_files.read_file, False),
    "write_file": (_files.write_file, False),
    "append_file": (_files.append_file, False),
    "delete_file": (_files.delete_file, False),
    "python": (_python.execute, False),
    "shell": (_shell.execute, False),
    "request_review": (_reconcile.request_review, True),
    "request_integration": (_reconcile.request_integration, True),
    "request_testing": (_reconcile.request_testing, True),
    "request_fix": (_reconcile.request_fix, True),
    "curl": (_web.curl, False),
    "search_web_cache": (_web.search_web_cache, False),
    "read_cached_page": (_web.read_cached_page, False),
    "open_terminal": (_terminals.open_terminal, False),
    "terminal_command": (_terminals.terminal_command, False),
    "close_terminal": (_terminals.close_terminal, False),
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
