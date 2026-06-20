"""council_rhetoric — the >>COUNCIL_RHETORIC<< arrow.

This function aggregates all the outputs of a council's members into one response
to give to each model. Each model will not receive their own response, but will
receive the response of every other model, all aggregated into a form like:

    Philosophy Agent:
    ~response~

    Coding Agent:
    ~response~

This function does not aggregate their entire chat, just the response they made
prior to convening (labeled AGENT_INPUT in the convergence explanation).
``ctx.rhetoric`` holds (agent_name, output) pairs for every member except the one
reading it.
"""
from __future__ import annotations


def council_rhetoric(ctx) -> str:
    if not ctx.rhetoric:
        return "(no other contributions yet)"
    parts = []
    for name, output in ctx.rhetoric:
        parts.append(f"{name}:\n{(output or '').strip()}")
    return "\n\n".join(parts)
