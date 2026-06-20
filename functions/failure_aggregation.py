"""failure_aggregation — the >>FAILURE_AGGREGATION<< arrow.

After a vote fails, this aggregates every OTHER member's full vote statement
(their reasoning plus their FINISHED/INCOMPLETE vote) into one block for a member
to read — the same idea as council_rhetoric, but over the vote statements. A
member never sees its own vote here; it already has it. ``ctx.failure_votes``
holds (agent_name, vote_statement) pairs for everyone except the reader.
"""
from __future__ import annotations


def failure_aggregation(ctx) -> str:
    if not ctx.failure_votes:
        return "(no other votes to read)"
    parts = []
    for name, statement in ctx.failure_votes:
        parts.append(f"{name}:\n{(statement or '').strip()}")
    return "\n\n".join(parts)
