"""Council assembly: parse spawning directives, run convergence, zip the result.

A council is the group of agents spawned to accomplish a single task. Each
member may, during reinitiation, spawn its own sub-council (EXPANSION → SPAWN);
that recursion is what lets the swarm go arbitrarily deep, bounded only by
``MAX_SUBSWARM_DEPTH``.
"""
from __future__ import annotations

import re

from . import ids
from .convergence import Member, run_convergence
from .runtime import Runtime
from .substitution import Context, resolve
from .zipper import run_zipper

# AGENT_TYPE: <short task>: <expanded explanation>
_DIRECTIVE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.+)$")

# The order council members act in. The model lists directives in an arbitrary
# order; we sort them into a sensible, deterministic pipeline-ish order so the
# producer (coding) goes before the checkers (testing/philosophizing). Unknown
# roles keep their listed order, after the known ones.
_ROLE_ORDER = {"coding": 0, "math": 1, "optimization": 2, "testing": 3,
               "philosophizing": 4}


def _truncate(text: str, words: int = 4) -> str:
    return " ".join((text or "").split()[:words])


def parse_directives(rt: Runtime, text: str) -> list[Member]:
    """Parse ``AGENT_TYPE: TASK: explanation`` lines into council members.
    Unknown agent types and malformed lines are skipped."""
    members: list[Member] = []
    for raw in (text or "").splitlines():
        m = _DIRECTIVE.match(raw)
        if not m:
            continue
        agent_type, rest = m.group(1), m.group(2)
        if not rt.instr.has_agent_type(agent_type):
            continue
        if ":" in rest:
            truncated, _, task = rest.partition(":")
            truncated, task = truncated.strip(), task.strip()
            if not truncated:
                truncated = _truncate(task)
        else:
            task = rest.strip()
            truncated = _truncate(task)
        members.append(Member(id=ids.next_id("agent"), agent_type=agent_type,
                              task=task, task_truncated=truncated))
    # Stable sort into a sensible acting order (coding first, checkers last).
    members.sort(key=lambda m: _ROLE_ORDER.get(m.agent_type, 99))
    return members


def run_council(rt: Runtime, members: list[Member], inherited: list[dict] | None,
                inherited_goal: str, council_dir, *, depth: int = 0) -> str:
    """Run a council to completion and return the zipped FINISHED OUTPUT.

    ``council_dir`` is this council's folder in the recursive log tree; each
    member's transcript, the votes log, the zipper file, and any sub-councils are
    written under it."""
    council_id = ids.next_id("council")
    max_depth = rt.settings.get_int("MAX_SUBSWARM_DEPTH", 4) or 4
    council_dir.mkdir(parents=True, exist_ok=True)
    for m in members:
        m.log_path = council_dir / f"{m.label}.txt"
    roster = ", ".join(m.agent_type for m in members)
    rt.logbook.chat(f"[{council_id}] council convening ({roster}) on: {inherited_goal[:60]}")

    def spawn_subcouncil(member: Member) -> str | None:
        if depth >= max_depth:
            return None
        ctx = Context(instr=rt.instr, agent_type=member.agent_type, task=member.task,
                      task_truncated=member.task_truncated, inherited_goal=inherited_goal)
        directive_text = rt.model.chat(
            member.agent_type,
            member.messages + [{"role": "user", "content": resolve(">>SPAWNING<<", ctx)}])
        sub_members = parse_directives(rt, directive_text)
        if not sub_members:
            return None
        # This agent's councils live beside its chat file, under <agent-id>-councils/.
        sub_dir = rt.next_council_dir(council_dir / f"{member.label}-councils")
        return run_council(rt, sub_members, list(member.messages), member.task,
                           sub_dir, depth=depth + 1)

    result = run_convergence(rt, members, inherited, inherited_goal, council_id,
                             council_dir=council_dir, spawn_subcouncil=spawn_subcouncil)
    payload = run_zipper(rt, result.final_outputs(), inherited, council_dir=council_dir,
                         task=inherited_goal, task_truncated=_truncate(inherited_goal))
    rt.logbook.chat(f"[{council_id}] council finished — result ready")
    return payload
