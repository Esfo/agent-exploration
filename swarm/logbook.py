"""Searchable logging + the one-line CLI status messages.

Votes are appended to ``logs/votes.jsonl`` (one JSON object per council round,
recording agent types and individual votes so they can be searched/tracked
later) and a single ``X-X`` YAY-NAY line is printed to the chat per vote.
"""
from __future__ import annotations

import json
import time
from pathlib import Path


def _short(text: str, limit: int = 80) -> str:
    """One-line, length-capped form for CLI status messages."""
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit].rstrip() + "..."


class Logbook:
    def __init__(self, log_dir: Path, sink=print):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.sink = sink
        self.append_sink = None   # optional: tack text onto the last printed line

    # ----- chat (one line each, not part of any agent's history) -----
    def chat(self, line: str) -> None:
        if self.sink is not None:
            self.sink(line)

    def append(self, suffix: str) -> None:
        """Tack ``suffix`` onto the last chat line (via the live display); falls
        back to emitting it as its own line."""
        if self.append_sink is not None:
            self.append_sink(suffix)
        else:
            self.chat(suffix.strip())

    # ----- jsonl -----
    def _append(self, name: str, obj: dict) -> None:
        obj = {"ts": time.time(), **obj}
        with (self.log_dir / name).open("a", encoding="utf-8") as f:
            f.write(json.dumps(obj) + "\n")

    # ----- votes -----
    def log_vote_round(self, council_id: str, inherited_goal: str, round_index: int,
                       votes: list[dict], tally) -> None:
        """``votes`` is ``[{"agent_id", "agent_type", "vote"}, ...]``."""
        self._append("votes.jsonl", {
            "council_id": council_id,
            "inherited_goal": inherited_goal,
            "round": round_index,
            "pattern": tally.pattern,
            "status": tally.status,
            "votes": votes,
        })
        self.chat(
            f"[{council_id}] round {round_index} vote {tally.pattern} (YAY-NAY) "
            f"- {tally.status} - goal: {_short(inherited_goal)}"
        )

    # ----- agent lifecycle (one line each) -----
    def agent_started(self, agent_type: str, task_truncated: str) -> None:
        self.chat(f"{agent_type} started {task_truncated}")

    def agent_finished(self, agent_type: str, task_truncated: str) -> None:
        self.chat(f"{agent_type} finished {task_truncated}")

    # ----- sandbox (one line each) -----
    def sandbox_run(self, label: str, lang: str) -> None:
        self.chat(f"{label} running {lang} in the sandbox...")

    def sandbox_done(self, label: str, lang: str, result) -> None:
        if result is None:
            status = "no runnable code"
        elif getattr(result, "timed_out", False):
            status = "timed out"
        else:
            status = f"exit {result.exit_code}"
        self.chat(f"{label} sandbox {lang} done - {status}")
