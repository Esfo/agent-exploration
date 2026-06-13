"""Memory store with enable/relevance toggles (spec section 13).

All memories are stored; only enabled and relevant ones are injected into a
model call. Relevance here is scope-based (global, a role name, or a swarm id)
plus optional tag/keyword overlap with the current task — deliberately simple
and deterministic.
"""
from __future__ import annotations

from datetime import datetime, timezone

from . import ids


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MemoryStore:
    def __init__(self, db):
        self.db = db

    def add(self, text: str, scope: str = "global", tags: str = "", enabled: bool = True) -> str:
        mem_id = ids.next_id("mem")
        self.db.conn.execute(
            "INSERT INTO memories (id, scope, tags, enabled, text, created_at) VALUES (?,?,?,?,?,?)",
            (mem_id, scope, tags, 1 if enabled else 0, text, _now()),
        )
        self.db.conn.commit()
        return mem_id

    def set_enabled(self, mem_id: str, enabled: bool) -> bool:
        cur = self.db.conn.execute(
            "UPDATE memories SET enabled=?, updated_at=? WHERE id=?",
            (1 if enabled else 0, _now(), mem_id),
        )
        self.db.conn.commit()
        return cur.rowcount > 0

    def all(self) -> list[dict]:
        rows = self.db.conn.execute("SELECT * FROM memories ORDER BY created_at").fetchall()
        return [dict(r) for r in rows]

    def relevant(self, *, role: str | None = None, swarm_id: str | None = None,
                 task: str = "", limit: int = 8) -> list[dict]:
        """Enabled memories whose scope matches, ranked by keyword overlap."""
        scopes = {"global"}
        if role:
            scopes.add(role)
        if swarm_id:
            scopes.add(swarm_id)
        rows = self.db.conn.execute(
            "SELECT * FROM memories WHERE enabled=1 ORDER BY created_at"
        ).fetchall()
        task_words = {w.lower() for w in task.split() if len(w) > 3}
        scored = []
        for r in rows:
            if r["scope"] not in scopes:
                continue
            tagset = {t.strip().lower() for t in (r["tags"] or "").split(",") if t.strip()}
            overlap = len(task_words & ({w.lower() for w in r["text"].split()} | tagset))
            scored.append((overlap, dict(r)))
        scored.sort(key=lambda x: -x[0])
        return [m for _, m in scored[:limit]]

    def render(self, memories: list[dict]) -> str:
        if not memories:
            return ""
        lines = ["MEMORIES (enabled, relevant):"]
        for m in memories:
            lines.append(f"  - {m['text']}")
        return "\n".join(lines)
