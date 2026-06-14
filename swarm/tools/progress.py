"""report_progress tool (spec section 5)."""
from __future__ import annotations


def execute(ctx, agent_id: str, args: dict) -> dict:
    agent = ctx.db.get_agent(agent_id)
    swarm_id = agent["swarm_id"] if agent else None
    message = args.get("message", "(no message)")
    completion = args.get("completion_percentage")
    current_step = args.get("current_step")
    payload = {
        "files_touched": args.get("files_touched", []),
    }
    if completion is not None:
        try:
            ctx.db.update_agent_completion(agent_id, float(completion))
        except (TypeError, ValueError):
            completion = None
    ctx.events.agent_progress(swarm_id, agent_id, message, completion, current_step, payload)
    return {"status": "ok", "recorded": True}
