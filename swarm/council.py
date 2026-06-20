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
from .voting import SPAWN_REMINDER, malformed_choice, parse_yes_no
from .zipper import run_zipper

# AGENT_TYPE: <short task>: <expanded explanation>
_DIRECTIVE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.+)$")

# The order council members act in. The model lists directives in an arbitrary
# order; we sort them into a sensible, deterministic pipeline-ish order so the
# producer (coding) goes before the checkers (testing/philosophizing). Unknown
# roles keep their listed order, after the known ones.
_ROLE_ORDER = {"coding": 0, "math": 1, "optimization": 2, "testing": 3,
               "philosophizing": 4}


# Dangling words a short task shouldn't end on.
_TRAILING = {"and", "or", "the", "a", "an", "to", "of", "for", "with", "in", "on"}


def _clean_short(text: str) -> str:
    """Tidy a short task label: drop trailing punctuation and dangling words."""
    words = (text or "").strip().rstrip(",.;:- ").split()
    while words and words[-1].lower().strip(",.;:") in _TRAILING:
        words.pop()
    return " ".join(words)


def _truncate(text: str, words: int = 4) -> str:
    return _clean_short(" ".join((text or "").split()[:words]))


def _strip_noise(line: str) -> str:
    """Strip leading list markers / numbering and surrounding markdown so a
    directive is recognized even when the model dresses it up."""
    line = line.strip()
    line = re.sub(r"^([-*+•]\s+|\d+[.)]\s+)", "", line)   # bullets / numbering
    line = line.replace("**", "").replace("`", "").replace("__", "")
    return line.strip()


def parse_directives(rt: Runtime, text: str) -> list[Member]:
    """Parse ``AGENT_TYPE: TASK: explanation`` lines into council members.
    Tolerant of markdown bullets/bold and agent-type capitalization; unknown
    agent types and malformed lines are skipped."""
    valid = {t.lower(): t for t in rt.instr.agent_types()}
    members: list[Member] = []
    for raw in (text or "").splitlines():
        m = _DIRECTIVE.match(_strip_noise(raw))
        if not m:
            continue
        agent_type, rest = m.group(1), m.group(2)
        canonical = valid.get(agent_type.lower())
        if canonical is None:
            continue
        agent_type = canonical
        if ":" in rest:
            # AGENT_TYPE: TASK: explanation -> the colon delineates the short
            # task (used verbatim) from its expanded explanation.
            truncated, _, task = rest.partition(":")
            truncated, task = truncated.strip(), task.strip()
            if not truncated:
                truncated = _truncate(task)
        else:
            # Malformed (no colon between task and explanation): fall back to a
            # word-count truncation of the whole thing.
            task = rest.strip()
            truncated = _truncate(task)
        members.append(Member(id=str(ids.next_num("agent")), agent_type=agent_type,
                              task=task, task_truncated=truncated))
    # Stable sort into a sensible acting order (coding first, checkers last).
    members.sort(key=lambda m: _ROLE_ORDER.get(m.agent_type, 99))
    return members


_RESUBMIT = ("Please resubmit in this exact format, as a single line\n"
             "AGENT_TYPE: TASK: EXPLANATION")


def _confirmation(members: list[Member]) -> str:
    lines = "\n".join(f"{m.agent_type}: {m.task_truncated}: {m.task}" for m in members)
    return ("This is what was collected, according to the requested formatting:\n\n"
            + lines +
            "\n\nIs this correct, and are these goals more narrow than any prior goals?\nExplicitly answer either YES or NO at the very end "
            "of your message.")


def collect_directives(rt: Runtime, spawn_prompt: str, ask, notice):
    """Get a council's directives from the model, then have it confirm them
    before spawning. ``ask(text) -> reply`` issues an (ephemeral) model turn;
    ``notice(text)`` logs a status line. Returns confirmed members, or None if a
    finite SPAWN_FORMAT_RETRIES cap is hit before parsing.

    Loop: parse (re-asking with the format reminder until it parses) -> echo the
    collected list and ask YES/NO -> on NO, ask for a resubmission and repeat;
    on YES, return the members."""
    max_tries = rt.settings.get_int("SPAWN_FORMAT_RETRIES", None)
    members = parse_directives(rt, ask(spawn_prompt))
    tries = 0
    while True:
        while not members:
            if max_tries and tries >= max_tries:
                return None
            tries += 1
            cap = f"/{max_tries}" if max_tries else ""
            notice(f"directives didn't match the expected format, "
                   f"asking again (try {tries}{cap})...")
            members = parse_directives(rt, ask(SPAWN_REMINDER + "\n" + spawn_prompt))
        # Confirmation step.
        verdict = ask(_confirmation(members))
        decision = parse_yes_no(verdict)
        c = 0
        while decision is None and c < 2:
            verdict = ask(malformed_choice("YES", "NO") + "\n" + _confirmation(members))
            decision = parse_yes_no(verdict)
            c += 1
        if decision:
            return members
        notice("the collected agent list was rejected; asking for a resubmission...")
        members = parse_directives(rt, ask(_RESUBMIT))


def run_council(rt: Runtime, members: list[Member], inherited: list[dict] | None,
                inherited_goal: str, council_dir, label: str, *, depth: int = 0) -> str:
    """Run a council to completion and return the zipped FINISHED OUTPUT.

    ``label`` is this council's hierarchical id (e.g. "1", "1.2", "1.2.3"); its
    sub-councils are "<label>.<n>". ``council_dir`` is this council's folder in
    the recursive log tree."""
    council_id = f"council {label}"
    max_depth = rt.settings.get_int("MAX_SUBSWARM_DEPTH", 4) or 4
    council_dir.mkdir(parents=True, exist_ok=True)
    for m in members:
        m.log_path = council_dir / f"{m.label}.txt"
    roster = ", ".join(m.label for m in members)
    rt.logbook.chat(f"[{council_id}] convening ({roster}) on: {inherited_goal[:60]}")

    child_count = [0]   # sub-councils spawned under THIS council, by any member

    def spawn_subcouncil(member: Member) -> str | None:
        if depth >= max_depth:
            return None
        ctx = Context(instr=rt.instr, agent_type=member.agent_type, task=member.task,
                      task_truncated=member.task_truncated, inherited_goal=inherited_goal)
        prompt = resolve(">>SPAWNING<<", ctx)

        def ask(text: str) -> str:
            return rt.model.chat(member.agent_type,
                                 member.messages + [{"role": "user", "content": text}])

        sub_members = collect_directives(
            rt, prompt, ask,
            lambda s: rt.logbook.chat(f"[{council_id}] {member.label}: {s}"))
        if not sub_members:
            return None
        child_count[0] += 1
        child_label = f"{label}.{child_count[0]}"
        roster = ", ".join(s.label for s in sub_members)
        rt.logbook.chat(f"[{council_id}] {member.label} spawning sub-council "
                        f"{child_label} ({roster}) for: {member.task[:60]}")
        # This agent's councils live beside its chat file, under <agent-id>-councils/.
        sub_dir = council_dir / f"{member.label}-councils" / f"council_{child_label}"
        return run_council(rt, sub_members, list(member.messages), member.task,
                           sub_dir, child_label, depth=depth + 1)

    result = run_convergence(rt, members, inherited, inherited_goal, council_id,
                             council_dir=council_dir, spawn_subcouncil=spawn_subcouncil)
    payload = run_zipper(rt, result.final_outputs(), inherited, council_dir=council_dir,
                         task=inherited_goal, task_truncated=_truncate(inherited_goal))
    rt.logbook.chat(f"[{council_id}] finished - result ready")
    return payload
