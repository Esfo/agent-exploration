"""SQLite state store (spec section 28).

Thin typed wrapper over sqlite3. One connection, WAL mode, row factory.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DB:
    def __init__(self, path: str | Path, schema_path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA foreign_keys=ON;")
        self._init_schema(schema_path)

    def _init_schema(self, schema_path: str | Path) -> None:
        sql = Path(schema_path).read_text(encoding="utf-8")
        self.conn.executescript(sql)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # ----- swarms -----
    def create_swarm(self, swarm_id: str, user_goal: str, root_agent_id: str | None = None) -> None:
        self.conn.execute(
            "INSERT INTO swarms (id, root_agent_id, user_goal, status, completion_percentage, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (swarm_id, root_agent_id, user_goal, "running", 0.0, _now()),
        )
        self.conn.commit()

    def set_swarm_root(self, swarm_id: str, root_agent_id: str) -> None:
        self.conn.execute("UPDATE swarms SET root_agent_id=? WHERE id=?", (root_agent_id, swarm_id))
        self.conn.commit()

    def update_swarm(self, swarm_id: str, *, status: str | None = None,
                     completion: float | None = None) -> None:
        if status is not None:
            self.conn.execute("UPDATE swarms SET status=? WHERE id=?", (status, swarm_id))
            if status in ("complete", "failed", "cancelled"):
                self.conn.execute("UPDATE swarms SET finished_at=? WHERE id=?", (_now(), swarm_id))
        if completion is not None:
            self.conn.execute(
                "UPDATE swarms SET completion_percentage=? WHERE id=?", (completion, swarm_id)
            )
        self.conn.commit()

    def get_swarm(self, swarm_id: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM swarms WHERE id=?", (swarm_id,)).fetchone()

    # ----- agents -----
    def create_agent(self, agent: dict[str, Any]) -> None:
        agent.setdefault("created_at", _now())
        agent.setdefault("status", "created")
        agent.setdefault("completion_percentage", 0.0)
        cols = ",".join(agent.keys())
        ph = ",".join("?" for _ in agent)
        self.conn.execute(f"INSERT INTO agents ({cols}) VALUES ({ph})", tuple(agent.values()))
        self.conn.commit()

    def update_agent_status(self, agent_id: str, status: str) -> None:
        self.conn.execute("UPDATE agents SET status=? WHERE id=?", (status, agent_id))
        if status == "started":
            self.conn.execute(
                "UPDATE agents SET started_at=COALESCE(started_at,?) WHERE id=?", (_now(), agent_id)
            )
        if status in ("complete", "blocked", "failed", "cancelled"):
            self.conn.execute("UPDATE agents SET finished_at=? WHERE id=?", (_now(), agent_id))
        self.conn.commit()

    def update_agent_completion(self, agent_id: str, pct: float) -> None:
        self.conn.execute(
            "UPDATE agents SET completion_percentage=? WHERE id=?", (pct, agent_id)
        )
        self.conn.commit()

    def get_agent(self, agent_id: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM agents WHERE id=?", (agent_id,)).fetchone()

    def list_children(self, parent_id: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM agents WHERE parent_agent_id=? ORDER BY created_at", (parent_id,)
        ).fetchall()

    def list_swarm_agents(self, swarm_id: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM agents WHERE swarm_id=? ORDER BY created_at", (swarm_id,)
        ).fetchall()

    def count_swarm_agents(self, swarm_id: str) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) AS c FROM agents WHERE swarm_id=?", (swarm_id,)
        ).fetchone()["c"]

    # ----- messages -----
    def save_message(self, agent_id: str, role: str, content: str) -> None:
        self.conn.execute(
            "INSERT INTO messages (agent_id, role, content, created_at) VALUES (?,?,?,?)",
            (agent_id, role, content, _now()),
        )
        self.conn.commit()

    def get_messages(self, agent_id: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM messages WHERE agent_id=? ORDER BY id", (agent_id,)
        ).fetchall()

    # ----- tool calls -----
    def save_tool_call(self, agent_id: str, tool_name: str, args: dict,
                       status: str, result: dict | None) -> None:
        self.conn.execute(
            "INSERT INTO tool_calls (agent_id, tool_name, args_json, status, result_json, created_at, finished_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (agent_id, tool_name, json.dumps(args), status,
             json.dumps(result) if result is not None else None, _now(), _now()),
        )
        self.conn.commit()

    # ----- model calls -----
    def save_model_call(self, agent_id: str, telemetry: dict) -> None:
        self.conn.execute(
            "INSERT INTO model_calls (agent_id, selected_model, endpoint, num_ctx, num_predict,"
            " temperature, prompt_eval_count, eval_count, duration_ms, done_reason, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                agent_id,
                telemetry.get("selected_model", "?"),
                telemetry.get("endpoint", "?"),
                telemetry.get("num_ctx"),
                telemetry.get("num_predict"),
                telemetry.get("temperature"),
                telemetry.get("prompt_eval_count"),
                telemetry.get("eval_count"),
                telemetry.get("duration_ms"),
                telemetry.get("done_reason"),
                _now(),
            ),
        )
        self.conn.commit()

    # ----- results -----
    def save_agent_result(self, agent_id: str, result: dict) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO agent_results (agent_id, status, summary, note, result_json, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (
                agent_id,
                result.get("status", "complete"),
                result.get("summary", ""),
                result.get("note", ""),
                json.dumps(result),
                _now(),
            ),
        )
        self.conn.commit()

    def get_agent_result(self, agent_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM agent_results WHERE agent_id=?", (agent_id,)
        ).fetchone()

    # ----- progress -----
    def save_progress(self, swarm_id: str | None, agent_id: str | None, message: str,
                      completion: float | None, current_step: str | None, payload: dict | None) -> None:
        self.conn.execute(
            "INSERT INTO progress_reports (swarm_id, agent_id, message, completion_percentage,"
            " current_step, payload_json, created_at) VALUES (?,?,?,?,?,?,?)",
            (swarm_id, agent_id, message, completion, current_step,
             json.dumps(payload) if payload else None, _now()),
        )
        self.conn.commit()

    # ----- checklists -----
    def create_checklist(self, agent_id: str, title: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO checklists (agent_id, title) VALUES (?,?)", (agent_id, title)
        )
        self.conn.commit()
        return cur.lastrowid

    def add_checklist_item(self, checklist_id: int, position: int, text: str,
                           weight: float = 1.0, assigned_child: str | None = None) -> int:
        cur = self.conn.execute(
            "INSERT INTO checklist_items (checklist_id, position, text, status, weight, assigned_child_agent_id)"
            " VALUES (?,?,?,?,?,?)",
            (checklist_id, position, text, "open", weight, assigned_child),
        )
        self.conn.commit()
        return cur.lastrowid

    def set_item_status(self, item_id: int, status: str) -> None:
        self.conn.execute(
            "UPDATE checklist_items SET status=? WHERE id=?", (status, item_id)
        )
        self.conn.commit()

    def get_checklist_items(self, agent_id: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT ci.* FROM checklist_items ci JOIN checklists c ON ci.checklist_id=c.id"
            " WHERE c.agent_id=? ORDER BY ci.position", (agent_id,)
        ).fetchall()
