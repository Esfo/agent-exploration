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
    work_root: Path           # hidden sandbox scratch root (workspace/.sandbox)
    primary_dir: Path         # root of the recursive log tree (workspace/primary)

    # ----- sandbox scratch (separate from the log tree) -----
    def agent_dir(self, agent_id: str) -> Path:
        """A hidden working directory for an agent's sandbox code execution."""
        d = self.work_root / agent_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    # ----- recursive log tree -----
    def write_transcript(self, path: Path, label: str, messages: list[dict]) -> None:
        """Write an agent's full conversation to ``path`` (rewritten as it grows)."""
        if not self.settings.get_bool("WRITE_TRANSCRIPTS", True):
            return
        out = [f"# {label}", ""]
        for m in messages:
            out.append(f"## {m.get('role', '?')}")
            out.append((m.get("content", "") or "").rstrip())
            out.append("")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(out), encoding="utf-8")

    def append_vote_log(self, council_dir: Path, round_index: int,
                        records: list[dict], tally) -> None:
        """Append a round's voting results to the council's votes log — only the
        votes and who cast them."""
        if not self.settings.get_bool("WRITE_TRANSCRIPTS", True):
            return
        council_dir.mkdir(parents=True, exist_ok=True)
        lines = [f"round {round_index}"]
        for r in records:
            who = f"{r['agent_type']}_{r['agent_id']}"
            lines.append(f"  {who}: {(r['vote'] or 'no-vote').upper()}")
        lines.append(f"  tally {tally.pattern} (YAY-NAY) - {tally.status}")
        lines.append("")
        with (council_dir / "votes.txt").open("a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    # ----- results library -----
    def save_result(self, goal: str, text: str) -> Path:
        from . import ids
        d = Path(self.settings.path("RESULTS_DIR"))
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{ids.next_id('result')}.md"
        path.write_text(f"# Result\n\n_Goal: {goal.strip()}_\n\n{text.strip()}\n",
                        encoding="utf-8")
        return path
