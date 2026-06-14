"""spawn_agents tool (spec section 15).

Validates the spawn request against recursion ceilings, creates child agent
records + working directories, resolves each child's model, and queues them.
The agent loop puts the parent into 'waiting_for_children' afterward.
"""
from __future__ import annotations

VALID_ROLES = {
    "planner", "spawner", "code", "terminal", "python", "shell", "researcher",
    "file_reader", "file_writer", "file_deleter", "reviewer", "integrator",
    "tester", "fixer", "profiler", "optimizer", "finisher",
}


def execute(ctx, agent_id: str, args: dict) -> dict:
    parent = ctx.db.get_agent(agent_id)
    if parent is None:
        return {"status": "error", "failure": "permission_denied", "detail": "no such parent"}

    children = args.get("children") or []
    if not isinstance(children, list) or not children:
        return {"status": "error", "failure": "invalid_tool_args",
                "detail": "spawn_agents requires a non-empty 'children' list"}

    # --- recursion ceilings (spec section 6) ---
    depth = int(parent["depth"])
    max_depth = ctx.settings.get_int("MAX_RECURSION_DEPTH")  # None == unlimited
    if max_depth is not None and depth + 1 > max_depth:
        return {"status": "blocked", "failure": "recursion_depth_exceeded",
                "detail": f"child depth {depth+1} exceeds MAX_RECURSION_DEPTH={max_depth}"}

    max_children = ctx.settings.get_int("MAX_CHILDREN_PER_AGENT")
    if max_children is not None and len(children) > max_children:
        children = children[:max_children]

    max_total = ctx.settings.get_int("MAX_TOTAL_AGENTS_PER_SWARM")
    if max_total is not None:
        existing = ctx.db.count_swarm_agents(parent["swarm_id"])
        room = max(0, max_total - existing)
        if room <= 0:
            return {"status": "blocked", "failure": "agent_budget_exhausted",
                    "detail": f"swarm reached MAX_TOTAL_AGENTS_PER_SWARM={max_total}"}
        children = children[:room]

    created = []
    for spec in children:
        role = str(spec.get("role", "code")).lower()
        if role not in VALID_ROLES:
            role = "code"
        child = ctx.create_child(
            parent=parent,
            title=str(spec.get("title", spec.get("task", "subtask"))[:200]),
            task=str(spec.get("task", "")),
            role=role,
            done_condition=str(spec.get("done_condition", "")),
            suggested_model=spec.get("suggested_model"),
            priority=int(spec.get("priority", 5)),
        )
        created.append({"id": child["id"], "title": child["title"], "role": role})

    ctx.events.spawn(agent_id, created)
    return {"status": "ok", "spawned": created, "count": len(created)}
