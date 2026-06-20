"""final_output — the >>FINAL_OUTPUT<< arrow.

This function aggregates the final output of each agent from the convergence
workflow to pass it onto the zipper workflow. Each agent's final output is
collected as it goes, tracked by a unique id per council, and updated every time
the agent makes a new one, so the last contribution of each agent is always on
hand when a vote passes. The outputs are presented to the zipper labeled by agent
and broken into numbered lines, like:

    AGENT_NAME
    line 1: ~information~
    line 2: ~information~

``ctx.final_outputs`` holds (agent_name, output) pairs.
"""
from __future__ import annotations


def final_output(ctx) -> str:
    parts = []
    for name, output in ctx.final_outputs:
        lines = (output or "").splitlines() or [""]
        body = "\n".join(f"line {i}: {ln}" for i, ln in enumerate(lines, 1))
        parts.append(f"{name}\n{body}")
    return "\n\n".join(parts)
