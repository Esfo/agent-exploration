"""The runtime bundle passed through the orchestration layer."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import ids
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

    def write_transcript(self, agent_id: str, agent_type: str, messages: list[dict]) -> None:
        """Persist an agent's full conversation to
        ``workspace/agents/<id>/conversation.md``, rewritten as it grows. This is
        the behind-the-scenes record of every turn the agent actually kept
        (ephemeral query turns are intentionally not part of it)."""
        if not self.settings.get_bool("WRITE_TRANSCRIPTS", True):
            return
        out = [f"# Conversation — {agent_type} ({agent_id})", ""]
        for m in messages:
            out.append(f"## {m.get('role', '?')}")
            out.append((m.get("content", "") or "").rstrip())
            out.append("")
        (self.agent_dir(agent_id) / "conversation.md").write_text(
            "\n".join(out), encoding="utf-8")

    def save_result(self, goal: str, text: str) -> Path:
        """Write a delivered result into the results library and return its path.

        The library is a flat directory of one Markdown file per result — no
        nested folders — so finished work is easy to find."""
        d = Path(self.settings.path("RESULTS_DIR"))
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{ids.next_id('result')}.md"
        path.write_text(f"# Result\n\n_Goal: {goal.strip()}_\n\n{text.strip()}\n",
                        encoding="utf-8")
        return path
