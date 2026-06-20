"""Real implementations of the ``>>...<<`` functions.

The text files under ``instructions/functions/`` are the human-readable
explanations of each of these; the executable versions live here and are wired
into the substitution engine (:mod:`swarm.substitution`).
"""
from __future__ import annotations

import re

# --------------------------------------------------------------------------
# Tools
# --------------------------------------------------------------------------
# The only official tool is the docker sandbox for running/testing code. It is
# granted to the agent types that produce or exercise code.
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


# --------------------------------------------------------------------------
# Substitution functions (called by swarm.substitution._lookup)
# --------------------------------------------------------------------------
def list_agent_types(ctx) -> str:
    """List every agent type and its purpose, formatted as::

        AGENT_TYPE: PURPOSE

        NEXT_AGENT_TYPE: PURPOSE
    """
    blocks = []
    for name in ctx.instr.agent_types():
        purpose = ctx.instr.agent_purpose(name).strip()
        blocks.append(f"{name}: {purpose}")
    return "\n\n".join(blocks)


def list_tools(ctx) -> str:
    """List the tools the current agent has access to."""
    tools = ctx.tools or tools_for(ctx.agent_type)
    if not tools:
        return "You have no tools available."
    return "\n".join(TOOL_DESCRIPTIONS.get(t, t) for t in tools)


def council_rhetoric(ctx) -> str:
    """Aggregate the OTHER members' contributions for one member to read::

        coding:
        ~response~

        philosophizing:
        ~response~
    """
    if not ctx.rhetoric:
        return "(no other contributions yet)"
    parts = []
    for name, output in ctx.rhetoric:
        parts.append(f"{name}:\n{(output or '').strip()}")
    return "\n\n".join(parts)


def final_output(ctx) -> str:
    """Format every agent's final output line-by-line for the zipper::

        AGENT_NAME
        line 1: ~text~
        line 2: ~text~
    """
    parts = []
    for name, output in ctx.final_outputs:
        lines = (output or "").splitlines() or [""]
        body = "\n".join(f"line {i}: {ln}" for i, ln in enumerate(lines, 1))
        parts.append(f"{name}\n{body}")
    return "\n\n".join(parts)


def document_display(ctx) -> str:
    """Show the zipper's current document with line numbers."""
    if not (ctx.document or "").strip():
        return "(the document is currently empty)"
    lines = ctx.document.splitlines()
    return "\n".join(f"{i}: {ln}" for i, ln in enumerate(lines, 1))


def return_output(ctx) -> str:
    """Return the last sandbox/shell output to the agent."""
    return ctx.shell_output or "(no output)"


# --------------------------------------------------------------------------
# Code-block recognition (for the convergence test/run loop)
# --------------------------------------------------------------------------
# Every language we recognise in a fenced ``` block, mapped to the canonical
# language key used by the sandbox runner.
LANG_ALIASES: dict[str, str] = {
    "python": "python", "py": "python", "python3": "python",
    "javascript": "node", "js": "node", "node": "node",
    "typescript": "ts", "ts": "ts",
    "ruby": "ruby", "rb": "ruby",
    "go": "go", "golang": "go",
    "rust": "rust", "rs": "rust",
    "c": "c",
    "cpp": "cpp", "c++": "cpp", "cxx": "cpp", "cc": "cpp",
    "java": "java",
    "kotlin": "kotlin", "kt": "kotlin",
    "scala": "scala",
    "swift": "swift",
    "php": "php",
    "perl": "perl", "pl": "perl",
    "lua": "lua",
    "r": "r",
    "julia": "julia", "jl": "julia",
    "haskell": "haskell", "hs": "haskell",
    "bash": "bash", "sh": "bash", "shell": "bash", "zsh": "bash",
    "sql": "sql",
}

_FENCE = re.compile(r"```([A-Za-z0-9+#.]*)[ \t]*\r?\n(.*?)```", re.DOTALL)


def extract_code_blocks(text: str) -> list[tuple[str, str]]:
    """Return ``[(canonical_lang, code), ...]`` for every fenced block whose
    language tag we recognise. Unlabelled or unknown blocks are skipped."""
    blocks = []
    for tag, body in _FENCE.findall(text or ""):
        lang = LANG_ALIASES.get(tag.strip().lower())
        if lang and body.strip():
            blocks.append((lang, body))
    return blocks


# --------------------------------------------------------------------------
# Final-output extraction (FINISHED OUTPUT marker)
# --------------------------------------------------------------------------
FINISHED_MARKER = "FINISHED OUTPUT"


def extract_finished_output(text: str) -> str:
    """Everything below a ``FINISHED OUTPUT`` line (matched as ``str.upper()``)
    is the agent's finalised contribution. If the marker is absent, the whole
    response is treated as the working contribution."""
    lines = (text or "").splitlines()
    for i, ln in enumerate(lines):
        if ln.strip().upper() == FINISHED_MARKER:
            return "\n".join(lines[i + 1:]).strip()
    return (text or "").strip()
