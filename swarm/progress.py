"""Progress / event reporting back to chat (spec sections 5, 31).

Emits human-readable events to a sink (stdout by default), appends structured
events to logs/*.jsonl, and records progress rows in the DB. Also computes
weighted completion for an agent subtree.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

# Default weights for completion accounting (spec section 31).
ROLE_WEIGHTS = {
    "checklist_item": 1.0,
    "code": 1.0,
    "researcher": 1.0,
    "profiler": 1.0,
    "optimizer": 2.0,
    "reviewer": 1.0,
    "tester": 2.0,
    "integrator": 2.0,
    "finisher": 2.0,
}


class EventBus:
    def __init__(self, log_dir: str | Path, db=None,
                 sink: Callable[[str], None] | None = None,
                 show: dict[str, bool] | None = None):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.db = db
        self.sink = sink or print
        self.show = show or {}

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _jsonl(self, name: str, record: dict) -> None:
        record = {"ts": self._now(), **record}
        with (self.log_dir / name).open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    def _shown(self, flag: str, default: bool = True) -> bool:
        return self.show.get(flag, default)

    # ----- chat-facing events -----
    def agent_started(self, agent: dict) -> None:
        self._jsonl("agents.jsonl", {"event": "agent_started", **agent})
        if not self._shown("CHAT_SHOW_AGENT_START"):
            return
        self.sink(
            f"\nAgent started: {agent['id']}\n"
            f"  Role: {agent['role']}\n"
            f"  Model: {agent.get('selected_model','?')} "
            f"({agent.get('execution_class','?')}, ctx={agent.get('num_ctx','?')})\n"
            f"  Task: {agent['task']}\n"
            f"  Parent: {agent.get('parent_agent_id') or 'user'}  Depth: {agent.get('depth',0)}\n"
            f"  Assigned directory: {agent.get('assigned_directory','?')}"
        )

    def agent_progress(self, swarm_id: str, agent_id: str, message: str,
                       completion: float | None, current_step: str | None = None,
                       payload: dict | None = None) -> None:
        self._jsonl("progress.jsonl", {
            "event": "progress_report", "swarm_id": swarm_id, "agent_id": agent_id,
            "message": message, "completion_percentage": completion,
            "current_step": current_step, "payload": payload,
        })
        if self.db:
            self.db.save_progress(swarm_id, agent_id, message, completion, current_step, payload)
        if not self._shown("CHAT_SHOW_AGENT_PROGRESS"):
            return
        pct = f" [{completion:.0f}%]" if completion is not None else ""
        self.sink(f"  · {agent_id}{pct}: {message}")

    def spawn(self, parent_id: str, children: list[dict]) -> None:
        self._jsonl("agents.jsonl", {"event": "spawn", "parent": parent_id, "children": children})
        if not self._shown("CHAT_SHOW_SPAWN_EVENTS"):
            return
        names = ", ".join(c.get("title", c.get("role", "child")) for c in children)
        self.sink(f"  ↳ {parent_id} spawned {len(children)} child agent(s): {names}")

    def agent_finished(self, agent_id: str, result: dict) -> None:
        self._jsonl("agents.jsonl", {"event": "agent_finished", "agent_id": agent_id, "result": result})
        if not self._shown("CHAT_SHOW_AGENT_FINISH"):
            return
        self.sink(
            f"\nAgent finished: {agent_id}\n"
            f"  Status: {result.get('status','complete')}\n"
            f"  Note: {result.get('note', result.get('summary',''))}\n"
            f"  Completion: {result.get('completion_percentage', 100)}%"
        )

    def chat(self, message: str) -> None:
        self._jsonl("chat.jsonl", {"event": "chat", "message": message})
        self.sink(message)


def subtree_completion(db, agent_id: str) -> float:
    """Weighted completion for an agent and its descendants.

    Leaf weight comes from role; a node's completion is its own stored
    percentage blended with the weighted average of its children.
    """
    agent = db.get_agent(agent_id)
    if agent is None:
        return 0.0
    children = db.list_children(agent_id)
    own = float(agent["completion_percentage"] or 0.0)
    if not children:
        return own
    total_w = 0.0
    acc = 0.0
    for ch in children:
        w = ROLE_WEIGHTS.get(ch["role"], 1.0)
        acc += w * subtree_completion(db, ch["id"])
        total_w += w
    child_pct = acc / total_w if total_w else 0.0
    # Parent's own work counts as one unit alongside its children.
    return round((own + child_pct * (total_w)) / (1 + total_w), 1)
