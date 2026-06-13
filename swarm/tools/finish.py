"""finish tool (spec sections 10, 14, 33).

Records the agent's final result and marks it complete/blocked/failed.
"""
from __future__ import annotations

_VALID = {"complete", "blocked", "failed"}


def execute(ctx, agent_id: str, args: dict) -> dict:
    status = str(args.get("status", "complete")).lower()
    if status not in _VALID:
        status = "complete"
    result = {
        "status": status,
        "summary": args.get("summary", ""),
        "note": args.get("note", args.get("summary", "")),
        "completion_percentage": args.get("completion_percentage", 100 if status == "complete" else 0),
        "files_created": args.get("files_created", []),
        "files_modified": args.get("files_modified", []),
        "files_deleted": args.get("files_deleted", []),
        "commands_run": args.get("commands_run", []),
        "sandboxes_used": args.get("sandboxes_used", []),
        "web_pages_used": args.get("web_pages_used", []),
        "remaining_issues": args.get("remaining_issues", []),
        "return_note": args.get("return_note", args.get("note", "")),
    }
    ctx.db.save_agent_result(agent_id, result)
    ctx.db.update_agent_completion(agent_id, float(result["completion_percentage"]))
    return result
