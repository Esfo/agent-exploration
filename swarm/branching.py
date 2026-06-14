"""Conversation/swarm branching (spec section 13).

A branch forks a swarm at a point in time: it copies the swarm's goal and the
root agent's prior messages (optionally up to a chosen message id) into a fresh
swarm + root agent. The branch has independent future messages, its own agent
tree, and its own completion state, while sharing the web cache.
"""
from __future__ import annotations

from . import ids


class BranchManager:
    def __init__(self, db):
        self.db = db

    def branch(self, swarm_id: str, at_message_id: int | None = None,
               note: str = "") -> dict:
        src = self.db.get_swarm(swarm_id)
        if src is None:
            return {"status": "error", "failure": "not_found", "detail": swarm_id}
        src_root = src["root_agent_id"]

        new_swarm = ids.next_id("swarm")
        goal = src["user_goal"] + (f"\n[branch note: {note}]" if note else "")
        self.db.create_swarm(new_swarm, goal)

        # Copy the root agent record (new id, fresh status/state).
        root_row = self.db.get_agent(src_root) if src_root else None
        new_root = ids.next_id("agent")
        if root_row:
            rec = dict(root_row)
            rec.update({
                "id": new_root, "swarm_id": new_swarm, "parent_agent_id": None,
                "status": "created", "completion_percentage": 0.0,
                "started_at": None, "finished_at": None,
            })
            rec.pop("created_at", None)  # let create_agent stamp a fresh one
            self.db.create_agent(rec)
        self.db.set_swarm_root(new_swarm, new_root)

        # Copy prior messages up to the branch point.
        copied = 0
        if src_root:
            with self.db.lock:
                rows = self.db.conn.execute(
                    "SELECT role, content, id FROM messages WHERE agent_id=? ORDER BY id",
                    (src_root,),
                ).fetchall()
            for r in rows:
                if at_message_id is not None and r["id"] > at_message_id:
                    break
                self.db.save_message(new_root, r["role"], r["content"])
                copied += 1

        return {"status": "ok", "branch_swarm_id": new_swarm, "root_agent_id": new_root,
                "copied_messages": copied, "from_swarm": swarm_id}

    def list_branches(self) -> list[dict]:
        rows = self.db.conn.execute(
            "SELECT id, user_goal, status, completion_percentage FROM swarms ORDER BY created_at"
        ).fetchall()
        return [dict(r) for r in rows]
