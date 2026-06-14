"""Instruction & prompt file loader.

Format:
    PURPOSE: ...
    001. ...
    002. ...

Each numbered line is an instruction the agent follows, kept in exact order.
Blank lines and '#' comments are ignored. The model for a role is chosen in
settings/main.settings, NOT in the instruction file. A legacy leading 'MODEL:'
line, if present, is accepted and ignored.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


class InstructionError(Exception):
    pass


@dataclass
class InstructionFile:
    path: Path
    purpose: str
    lines: list[str] = field(default_factory=list)        # numbered instructions, in order
    # Non-numbered free text (used by prompt files like agent_base.txt).
    body: list[str] = field(default_factory=list)

    def render(self) -> str:
        """Render the instruction content for injection into a prompt."""
        out: list[str] = []
        if self.purpose:
            out.append(f"PURPOSE: {self.purpose}")
        for i, ln in enumerate(self.lines, 1):
            out.append(f"{i:03d}. {ln}")
        out.extend(self.body)
        return "\n".join(out)


def parse_instruction_file(path: str | Path) -> InstructionFile:
    path = Path(path)
    if not path.exists():
        raise InstructionError(f"instruction file not found: {path}")
    raw_lines = path.read_text(encoding="utf-8").splitlines()

    purpose = ""
    numbered: list[str] = []
    body: list[str] = []

    for raw in raw_lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("MODEL:"):
            continue  # legacy line; the model comes from settings now
        if stripped.startswith("PURPOSE:"):
            purpose = stripped[len("PURPOSE:"):].strip()
            continue
        head, sep, rest = stripped.partition(".")
        if sep and head.strip().isdigit():
            numbered.append(rest.strip())
        else:
            body.append(raw.rstrip())

    return InstructionFile(path=path, purpose=purpose, lines=numbered, body=body)


def load_all(settings, keys: list[str]) -> dict[str, InstructionFile]:
    """Load a set of instruction files by their settings keys."""
    loaded: dict[str, InstructionFile] = {}
    for key in keys:
        rel = settings.get(key)
        if not rel:
            continue
        loaded[key] = parse_instruction_file(settings.root / rel)
    return loaded
