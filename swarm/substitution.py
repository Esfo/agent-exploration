"""The ``>>ARROW<<`` substitution engine — the chat parser.

Instruction/query/convergence/zipper files contain ``>>NAME<<`` markers. This
engine resolves them against a :class:`Context`, pulling values from three
kinds of source:

1. **Scalar context values** — ``>>AGENT_TYPE<<``, ``>>TASK<<``,
   ``>>TASK_TRUNCATED<<``, ``>>INHERITED_GOAL<<``.
2. **Other instruction files** — ``>>PURPOSE<<`` (the agent's own instruction
   file), ``>>SPAWNING<<``/``>>EXPANSION<<`` (queries), ``>>CONVERGENCE_VOTE<<``
   (a convergence prompt), ``>>INITIATION<<`` (the zipper initiation).
3. **Functions** — ``>>LIST_AGENT_TYPES<<``, ``>>LIST_TOOLS<<``,
   ``>>COUNCIL_RHETORIC<<``, ``>>DOCUMENT_DISPLAY<<``, ``>>FINAL_OUTPUT<<``,
   ``>>RETURN_OUTPUT<<`` (implemented in :mod:`swarm.functions`).

Resolution is recursive (a file pulled in by one arrow may contain its own
arrows) with a depth guard. ``>>INHERITED GOAL<<`` (with a space) normalises to
the same token as ``>>INHERITED_GOAL<<``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .instructions import Instructions

_ARROW = re.compile(r">>\s*([A-Za-z][A-Za-z0-9 _]*?)\s*<<")
_MAX_DEPTH = 12


@dataclass
class Context:
    """Everything the arrow resolvers may need for the current phase."""

    instr: Instructions
    agent_type: str = ""
    task: str = ""
    task_truncated: str = ""
    inherited_goal: str = ""

    # Populated per phase by the convergence / zipper engines.
    rhetoric: list[tuple[str, str]] = field(default_factory=list)   # (agent_name, output) of OTHERS
    final_outputs: list[tuple[str, str]] = field(default_factory=list)  # (agent_name, output)
    document: str = ""             # current zipper document
    shell_output: str = ""         # last sandbox output (for RETURN_OUTPUT)
    tools: list[str] = field(default_factory=list)


def _normalize(name: str) -> str:
    return name.strip().upper().replace(" ", "_")


def resolve(text: str, ctx: Context, *, _depth: int = 0) -> str:
    """Replace every ``>>ARROW<<`` in ``text`` using ``ctx``. Unknown arrows are
    left untouched so a typo never silently erases content."""
    if _depth > _MAX_DEPTH or "<<" not in text:
        return text

    # Imported lazily to avoid an import cycle (functions -> substitution).
    from . import functions

    def repl(match: re.Match) -> str:
        name = _normalize(match.group(1))
        value = _lookup(name, ctx, functions)
        if value is None:
            return match.group(0)  # leave unknown arrows verbatim
        return resolve(value, ctx, _depth=_depth + 1)

    return _ARROW.sub(repl, text)


def _lookup(name: str, ctx: Context, functions) -> str | None:
    # --- scalar values ---
    scalars = {
        "AGENT_TYPE": ctx.agent_type,
        "TASK": ctx.task,
        "TASK_TRUNCATED": ctx.task_truncated,
        "INHERITED_GOAL": ctx.inherited_goal,
    }
    if name in scalars:
        return scalars[name]

    # --- other instruction files ---
    if name == "PURPOSE":
        return ctx.instr.agent_purpose(ctx.agent_type) if ctx.agent_type else ""
    if name == "SPAWNING":
        return ctx.instr.read("queries", "spawning")
    if name == "EXPANSION":
        return ctx.instr.read("queries", "expansion")
    if name == "CONVERGENCE_VOTE":
        return ctx.instr.read("convergence", "vote")
    if name == "INITIATION":
        return ctx.instr.read("zipper", "initiate")

    # --- functions ---
    if name == "LIST_AGENT_TYPES":
        return functions.list_agent_types(ctx)
    if name == "LIST_TOOLS":
        return functions.list_tools(ctx)
    if name == "COUNCIL_RHETORIC":
        return functions.council_rhetoric(ctx)
    if name == "DOCUMENT_DISPLAY":
        return functions.document_display(ctx)
    if name == "FINAL_OUTPUT":
        return functions.final_output(ctx)
    if name == "RETURN_OUTPUT":
        return functions.return_output(ctx)

    return None
