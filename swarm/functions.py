"""Internal helpers + the loader for the ``>>...<<`` arrow functions.

The arrow functions themselves live as real Python in the
``instructions/functions/`` files (``LIST_AGENT_TYPES``, ``LIST_TOOLS``,
``COUNCIL_RHETORIC``, ``FINAL_OUTPUT``, ``DOCUMENT_DISPLAY``, ``RETURN_OUTPUT``).
Each such file is the explanation (as comments) plus the function definition; the
loader here execs the file and calls the function it defines, giving the
substitution engine a single entry point per arrow. The helpers below (the tool
registry, code-block recognition, FINISHED OUTPUT extraction) are runtime
support, not arrow functions, so they stay in the module.
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
# Arrow-function loader
# --------------------------------------------------------------------------
# The names match the instruction files under instructions/functions/.
_ARROW_FILES = {
    "list_agent_types": "LIST_AGENT_TYPES",
    "list_tools": "LIST_TOOLS",
    "council_rhetoric": "COUNCIL_RHETORIC",
    "final_output": "FINAL_OUTPUT",
    "document_display": "DOCUMENT_DISPLAY",
    "return_output": "RETURN_OUTPUT",
}

# Helpers made available to the function files when they are exec'd.
_INJECT = {"tools_for": tools_for, "has_tools": has_tools,
           "TOOLS_BY_TYPE": TOOLS_BY_TYPE, "TOOL_DESCRIPTIONS": TOOL_DESCRIPTIONS}

_cache: dict[str, callable] = {}


def _load(instr, filename: str):
    """Exec ``instructions/functions/<filename>`` and return the function it
    defines (the one new callable created by the file)."""
    if filename in _cache:
        return _cache[filename]
    path = instr.root / "functions" / filename
    ns = dict(_INJECT)
    before = set(ns)
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), ns)  # noqa: S102
    defined = [v for k, v in ns.items() if k not in before and callable(v)]
    if not defined:
        raise RuntimeError(f"{path} does not define a function")
    fn = defined[0]
    _cache[filename] = fn
    return fn


def _call(name: str, ctx):
    return _load(ctx.instr, _ARROW_FILES[name])(ctx)


# Thin wrappers so the substitution engine has a stable Python interface; each
# dispatches to the real function loaded from the instruction file.
def list_agent_types(ctx) -> str: return _call("list_agent_types", ctx)
def list_tools(ctx) -> str: return _call("list_tools", ctx)
def council_rhetoric(ctx) -> str: return _call("council_rhetoric", ctx)
def final_output(ctx) -> str: return _call("final_output", ctx)
def document_display(ctx) -> str: return _call("document_display", ctx)
def return_output(ctx) -> str: return _call("return_output", ctx)


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
