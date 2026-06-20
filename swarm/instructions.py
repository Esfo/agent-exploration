"""Instruction-file loader.

Every instruction file is ONE prompt. The whole file is its content (no
numbered lines, no ``PURPOSE:`` prefix) and it is always used together. This
module just reads files verbatim and discovers the available agent types.

Layout under ``instructions/``::

    system                      system-wide prompt (before every role prompt,
                                except the zipper)
    primary/agent               the primary (plan-setting) agent
    coding, math, ...           one file per agent type (the whole file is the
                                agent's purpose)
    convergence/<name>          the hard-coded convergence prompts
    queries/<name>              repeatable single-prompt queries (spawning, ...)
    zipper/<name>               the zipper workflow prompts
    functions/<name>            explanations for the real functions in
                                ``swarm/functions.py`` (not loaded as prompts)

Agent types are simply the top-level files in ``instructions/`` other than
``system`` (directories are reserved for the workflows above).
"""
from __future__ import annotations

from pathlib import Path

# Files that are top-level but are NOT agent types.
_NON_AGENT_FILES = {"system"}


class InstructionError(Exception):
    pass


class Instructions:
    """Reads instruction files relative to the ``instructions/`` directory."""

    def __init__(self, root: Path):
        self.root = Path(root)
        if not self.root.is_dir():
            raise InstructionError(f"instructions directory not found: {self.root}")

    def read(self, *parts: str) -> str:
        """Return the verbatim text of an instruction file, e.g.
        ``read("convergence", "vote")`` or ``read("coding")``."""
        path = self.root.joinpath(*parts)
        if not path.is_file():
            raise InstructionError(f"instruction file not found: {path}")
        return path.read_text(encoding="utf-8").rstrip("\n")

    def system(self) -> str:
        return self.read("system")

    def agent_purpose(self, agent_type: str) -> str:
        """The whole instruction file for an agent type IS its purpose."""
        return self.read(agent_type)

    def agent_types(self) -> list[str]:
        """Every top-level instruction file that names an agent type."""
        out = []
        for p in sorted(self.root.iterdir()):
            if p.is_file() and p.name not in _NON_AGENT_FILES:
                out.append(p.name)
        return out

    def has_agent_type(self, agent_type: str) -> bool:
        return (self.root / agent_type).is_file() and agent_type not in _NON_AGENT_FILES
