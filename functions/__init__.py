"""The >>...<< arrow functions, as real importable Python.

Each arrow function lives in its own ``.py`` module here (the module docstring is
its explanation, the function is the implementation). They are reached from the
substitution engine via :mod:`swarm.functions`, which re-exports them alongside
the runtime helpers (code-block recognition, FINISHED OUTPUT extraction).
"""
from .council_rhetoric import council_rhetoric
from .document_display import document_display
from .final_output import final_output
from .list_agent_types import list_agent_types
from .list_tools import list_tools
from .return_output import return_output
from .tools import (SANDBOX_TOOL, TOOL_DESCRIPTIONS, TOOLS_BY_TYPE, has_tools,
                    tools_for)

__all__ = [
    "council_rhetoric", "document_display", "final_output", "list_agent_types",
    "list_tools", "return_output",
    "SANDBOX_TOOL", "TOOL_DESCRIPTIONS", "TOOLS_BY_TYPE", "has_tools", "tools_for",
]
