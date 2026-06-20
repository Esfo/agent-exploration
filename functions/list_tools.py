"""list_tools — the >>LIST_TOOLS<< arrow.

This function lists all the tools that a specific agent has access to. The tools
are defined in TOOLS_BY_TYPE (functions/tools.py), keyed by agent type. For now
this is just the docker sandbox, granted to the coding, testing, optimization,
and math agents that can run and test things in docker.
"""
from __future__ import annotations

from .tools import TOOL_DESCRIPTIONS, tools_for


def list_tools(ctx) -> str:
    tools = ctx.tools or tools_for(ctx.agent_type)
    if not tools:
        return "You have no tools available."
    return "\n".join(TOOL_DESCRIPTIONS.get(t, t) for t in tools)
