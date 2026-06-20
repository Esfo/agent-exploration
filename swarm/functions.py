"""Bridge to the ``functions`` package + runtime helpers.

The six ``>>...<<`` arrow functions are real importable Python in the top-level
``functions`` package; they are re-exported here so the rest of the runtime has a
single ``swarm.functions`` import point. The helpers below (per-language
code-block recognition and FINISHED OUTPUT extraction) are runtime support, not
arrow functions, so they live here.
"""
from __future__ import annotations

import re

# Re-export the arrow functions + tool registry from the functions package.
from functions import (  # noqa: F401
    SANDBOX_TOOL, TOOL_DESCRIPTIONS, TOOLS_BY_TYPE, council_rhetoric,
    document_display, failure_aggregation, final_output, has_tools,
    list_agent_types, list_tools, return_output, tools_for)

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
