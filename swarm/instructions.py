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

import re
from dataclasses import dataclass, field
from pathlib import Path

from .settings import PLACEHOLDER_MODEL

# A check line may carry a machine-check tag, e.g.
#   003. A file was created for the deliverable. [[auto:created_a_file]]
# The tag names a deterministic check in swarm/checks.py; untagged lines are
# judged by the model. The tag is stripped from the text shown to the model.
_AUTO_TAG = re.compile(r"\s*\[\[auto:([a-zA-Z0-9_]+)\]\]\s*$")


class InstructionError(Exception):
    pass


@dataclass
class Check:
    position: int
    text: str
    auto_key: str | None = None


@dataclass
class InstructionFile:
    path: Path
    model: str
    purpose: str
    lines: list[str] = field(default_factory=list)        # check text, tag-stripped
    checks: list[Check] = field(default_factory=list)      # ordered checks w/ optional auto_key
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
    checks: list[Check] = []
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
        # Numbered check line: "NNN. text [[auto:key]]"
        head, sep, rest = stripped.partition(".")
        if sep and head.strip().isdigit():
            rest = rest.strip()
            auto_key = None
            m = _AUTO_TAG.search(rest)
            if m:
                auto_key = m.group(1)
                rest = _AUTO_TAG.sub("", rest).rstrip()
            numbered.append(rest)
            checks.append(Check(position=int(head.strip()), text=rest, auto_key=auto_key))
        else:
            body.append(raw.rstrip())

    if model is None:
        raise InstructionError(f"{path}: no MODEL: line found")
    return InstructionFile(path=path, model=model, purpose=purpose, lines=numbered,
                           checks=checks, body=body)


def load_all(settings, keys: list[str]) -> dict[str, InstructionFile]:
    """Load a set of instruction files by their settings keys."""
    loaded: dict[str, InstructionFile] = {}
    for key in keys:
        rel = settings.get(key)
        if not rel:
            continue
        loaded[key] = parse_instruction_file(settings.root / rel)
    return loaded
