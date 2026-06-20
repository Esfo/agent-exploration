"""return_output — the >>RETURN_OUTPUT<< arrow.

This function returns shell output back to the agent that asked for code to be
run. During the convergence test loop, hard-coded python lifts the code blocks
out of the agent's response, runs them in the docker sandbox, and feeds whatever
the shell printed back through this function. The agent only receives what was
printed, so it should add debugging print statements to inspect the input and
output it cares about. ``ctx.shell_output`` holds the captured output of the last
sandbox run.
"""
from __future__ import annotations


def return_output(ctx) -> str:
    return ctx.shell_output or "(no output)"
