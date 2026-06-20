"""Tool registry: which agent types may use which tools.

The only official tool is the docker sandbox for running/testing code, granted to
the agent types that produce or exercise code.
"""
from __future__ import annotations

SANDBOX_TOOL = "docker_sandbox"

TOOLS_BY_TYPE: dict[str, list[str]] = {
    "coding": [SANDBOX_TOOL],
    "testing": [SANDBOX_TOOL],
    "optimization": [SANDBOX_TOOL],
    "math": [SANDBOX_TOOL],
}

TOOL_DESCRIPTIONS = {
    SANDBOX_TOOL: ("docker_sandbox — run/test code in the hardened Docker "
                   "sandbox. Put the code in a fenced code block and it is "
                   "executed; only what is printed comes back to you."),
}


def tools_for(agent_type: str) -> list[str]:
    return list(TOOLS_BY_TYPE.get(agent_type, []))


def has_tools(agent_type: str) -> bool:
    return bool(TOOLS_BY_TYPE.get(agent_type))
