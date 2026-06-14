"""Reconciliation request tools (spec section 27).

request_review / request_integration / request_testing / request_fix each spawn
exactly one child agent of the matching role and let the runtime run it. They
return a {"spawned": [...]} payload, which the agent loop runs to completion and
feeds back — the same machinery as spawn_agents.
"""
from __future__ import annotations


def _spawn_one(ctx, agent_id: str, args: dict, role: str, verb: str) -> dict:
    parent = ctx.db.get_agent(agent_id)
    if parent is None:
        return {"status": "error", "failure": "permission_denied", "detail": "no such parent"}

    # Depth ceiling check (mirrors spawn_agents).
    depth = int(parent["depth"])
    max_depth = ctx.settings.get_int("MAX_RECURSION_DEPTH")
    if max_depth is not None and depth + 1 > max_depth:
        return {"status": "blocked", "failure": "recursion_depth_exceeded",
                "detail": f"child depth {depth+1} exceeds MAX_RECURSION_DEPTH={max_depth}"}

    max_total = ctx.settings.get_int("MAX_TOTAL_AGENTS_PER_SWARM")
    if max_total is not None and ctx.db.count_swarm_agents(parent["swarm_id"]) >= max_total:
        return {"status": "blocked", "failure": "agent_budget_exhausted",
                "detail": f"swarm reached MAX_TOTAL_AGENTS_PER_SWARM={max_total}"}

    target = str(args.get("target", "") or args.get("task", "")).strip()
    detail = str(args.get("context", "")).strip()
    task = f"{verb}:\n{target}"
    if detail:
        task += f"\n\nContext from parent:\n{detail}"

    child = ctx.create_child(
        parent=parent,
        title=str(args.get("title", f"{role} pass"))[:200],
        task=task,
        role=role,
        done_condition=str(args.get("done_condition", f"{role} pass complete with a clear result")),
        suggested_model=args.get("suggested_model"),
        priority=int(args.get("priority", 6)),
    )
    ctx.events.spawn(agent_id, [{"id": child["id"], "title": child["title"], "role": role}])
    return {"status": "ok", "spawned": [{"id": child["id"], "title": child["title"], "role": role}]}


def request_review(ctx, agent_id, args):
    return _spawn_one(ctx, agent_id, args, "reviewer", "Review this work against its task")


def request_integration(ctx, agent_id, args):
    return _spawn_one(ctx, agent_id, args, "integrator", "Integrate these outputs")


def request_testing(ctx, agent_id, args):
    return _spawn_one(ctx, agent_id, args, "tester", "Test this work")


def request_fix(ctx, agent_id, args):
    return _spawn_one(ctx, agent_id, args, "fixer", "Fix this specific failure")
