"""Instruction & prompt file loader (spec sections 8, 9, 10).

Format:
    MODEL: <model or placeholder>
    PURPOSE: ...
    001. ...
    002. ...

Line 1 must start with MODEL:. Line 2 should start with PURPOSE:. Numbered
instruction lines are kept in exact order. Blank lines and '#' comments are
ignored (but do not reset ordering).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .settings import PLACEHOLDER_MODEL


class InstructionError(Exception):
    pass


@dataclass
class InstructionFile:
    path: Path
    model: str
    purpose: str
    lines: list[str] = field(default_factory=list)
    # Non-numbered free text (used by prompt files like agent_base.txt).
    body: list[str] = field(default_factory=list)

    @property
    def model_is_placeholder(self) -> bool:
        return self.model.strip() == PLACEHOLDER_MODEL

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

    model: str | None = None
    purpose = ""
    numbered: list[str] = []
    body: list[str] = []

    for raw in raw_lines:
        stripped = raw.strip()
        if model is None:
            # First non-empty line must be MODEL:
            if not stripped:
                continue
            if not stripped.startswith("MODEL:"):
                raise InstructionError(
                    f"{path}: first content line must start with 'MODEL:', got {raw!r}"
                )
            model = stripped[len("MODEL:"):].strip()
            continue
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("PURPOSE:"):
            purpose = stripped[len("PURPOSE:"):].strip()
            continue
        # Numbered instruction line: "NNN. text"
        head, sep, rest = stripped.partition(".")
        if sep and head.strip().isdigit():
            numbered.append(rest.strip())
        else:
            body.append(raw.rstrip())

    if model is None:
        raise InstructionError(f"{path}: no MODEL: line found")
    return InstructionFile(path=path, model=model, purpose=purpose, lines=numbered, body=body)


def load_all(settings, keys: list[str]) -> dict[str, InstructionFile]:
    """Load a set of instruction files by their settings keys."""
    loaded: dict[str, InstructionFile] = {}
    for key in keys:
        rel = settings.get(key)
        if not rel:
            continue
        loaded[key] = parse_instruction_file(settings.root / rel)
    return loaded
