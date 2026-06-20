"""Searchable logging + the one-line CLI status messages.

Votes are appended to ``logs/votes.jsonl`` (one JSON object per council round,
recording agent types and individual votes so they can be searched/tracked
later) and a single ``X-X`` YAY-NAY line is printed to the chat per vote.
"""
from __future__ import annotations

import json
import time
from pathlib import Path


class Logbook:
    def __init__(self, log_dir: Path, sink=print):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.sink = sink

    # ----- chat (one line each, not part of any agent's history) -----
    def chat(self, line: str) -> None:
        if self.sink is not None:
            self.sink(line)

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
            f"— {tally.status} — goal: {inherited_goal}"
        )

    # ----- agent lifecycle (one line each) -----
    def agent_started(self, agent_type: str, task_truncated: str) -> None:
        self.chat(f"{agent_type} started {task_truncated}")

    def agent_finished(self, agent_type: str, task_truncated: str) -> None:
        self.chat(f"{agent_type} finished {task_truncated}")
