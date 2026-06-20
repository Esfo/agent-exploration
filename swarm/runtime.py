"""The runtime bundle passed through the orchestration layer."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .instructions import Instructions
from .logbook import Logbook
from .model import Model


@dataclass
class Runtime:
    settings: object
    model: Model
    instr: Instructions
    logbook: Logbook
    executor: object          # sandbox Executor
    work_root: Path           # workspace/agents

    def agent_dir(self, agent_id: str) -> Path:
        d = self.work_root / agent_id
        d.mkdir(parents=True, exist_ok=True)
        return d
