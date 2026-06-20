"""The convergence process.

This is the hard-coded loop that drives a spawned council of agents toward a
finished answer to their inherited goal. The prompt wording lives in the
``instructions/convergence/`` files; this module concatenates and sequences them
exactly as specified and runs the response → test → convene → vote → (reinitiate)
loop until every member votes FINISHED.

Per member, the opening turn is one concatenated prompt::

    CONVERGENCE_INITIATION
    PURPOSE                (the agent's instruction file)
    TASK: <task>
    CONVERGENCE_ACTION

with the system instruction delivered as the system message and the spawning
conversation inherited ahead of it. The member then produces AGENT_INPUT;
tool-bearing members may run a CONVERGENCE_TEST loop in the sandbox first. Once
every member has contributed, all members read each other's work
(CONVERGENCE_CONVENE) and vote (CONVERGENCE_VOTE). A non-unanimous round feeds
back the collective reasoning (vote-failed), lets each member WAIT or CONTINUE
(reinitiate), and — on CONTINUE — re-runs the action and offers EXPANSION
(CONTINUE working alone, or SPAWN a sub-council). The loop then repeats.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import functions
from .runtime import Runtime
from .sandbox import format_result, run_code
from .substitution import Context, resolve
from .voting import (INCOMPLETE, MALFORMED_REPLY, parse_vote, tally_votes)

_RETRY = 2
_TEST_MAX_STEPS = 4


@dataclass
class Member:
    id: str
    agent_type: str
    task: str
    task_truncated: str
    messages: list[dict] = field(default_factory=list)
    final_output: str = ""
    vote: str | None = None
    waiting: bool = False
    log_path: object = None        # Path to this member's transcript file

    @property
    def label(self) -> str:
        return f"{self.agent_type}_{self.id}"


@dataclass
class ConvergenceResult:
    council_id: str
    inherited_goal: str
    status: str                       # FINISHED (always, possibly force-resolved)
    rounds: int
    members: list[Member]
    force_resolved: bool = False

    def final_outputs(self) -> list[tuple[str, str]]:
        """Each member's last contribution, labelled by agent type + id."""
        return [(f"{m.agent_type} ({m.id})", m.final_output) for m in self.members]


def _ctx(rt: Runtime, m: Member, goal: str, **extra) -> Context:
    c = Context(instr=rt.instr, agent_type=m.agent_type, task=m.task,
                task_truncated=m.task_truncated, inherited_goal=goal,
                tools=functions.tools_for(m.agent_type))
    for k, v in extra.items():
        setattr(c, k, v)
    return c


def _ask(rt: Runtime, m: Member, prompt: str) -> str:
    m.messages.append({"role": "user", "content": prompt})
    reply = rt.model.chat(m.agent_type, m.messages)
    m.messages.append({"role": "assistant", "content": reply})
    if m.log_path is not None:
        rt.write_transcript(m.log_path, m.label, m.messages)
    return reply


def _last_word_choice(text: str, options: tuple[str, ...]) -> str | None:
    """Return whichever option appears last in the text (case-insensitive)."""
    upper = (text or "").upper()
    best, best_pos = None, -1
    for opt in options:
        pos = upper.rfind(opt)
        if pos > best_pos:
            best, best_pos = opt, pos
    return best


def _required_choice(rt: Runtime, m: Member, prompt: str,
                     options: tuple[str, ...]) -> str | None:
    """Ask ``prompt`` and return one of ``options`` (last-word-wins). If the
    reply contains neither, re-ask with the malformed-input reply, bounded by
    ``_RETRY`` — the hard-coded format catch for required-choice turns."""
    reply = _ask(rt, m, prompt)
    choice = _last_word_choice(reply, options)
    tries = 0
    while choice is None and tries < _RETRY:
        reply = _ask(rt, m, MALFORMED_REPLY + "\n" + prompt)
        choice = _last_word_choice(reply, options)
        tries += 1
    return choice


def _ask_query(rt: Runtime, m: Member, prompt: str) -> str:
    """Ask a QUERY turn (queries/*) WITHOUT persisting it to the member's
    history — queries are ephemeral; only their result is kept (spec)."""
    return rt.model.chat(m.agent_type, m.messages + [{"role": "user", "content": prompt}])


def _query_choice(rt: Runtime, m: Member, prompt: str, options: tuple[str, ...]) -> str | None:
    """Ephemeral required-choice for a query turn (e.g. EXPANSION)."""
    reply = _ask_query(rt, m, prompt)
    choice = _last_word_choice(reply, options)
    tries = 0
    while choice is None and tries < _RETRY:
        reply = _ask_query(rt, m, MALFORMED_REPLY + "\n" + prompt)
        choice = _last_word_choice(reply, options)
        tries += 1
    return choice


# --------------------------------------------------------------------------
# Phases
# --------------------------------------------------------------------------
def _initiation(rt: Runtime, m: Member, goal: str, inherited: list[dict]) -> None:
    ctx = _ctx(rt, m, goal)
    m.messages = list(inherited or [])
    # One concatenated opening message, in spec order, after the inherited
    # history: CONVERGENCE_INITIATION, SYSTEM, PURPOSE, TASK, CONVERGENCE_ACTION.
    sections = [
        resolve(rt.instr.read("convergence", "initiation"), ctx),
        rt.instr.system(),
        resolve(">>PURPOSE<<", ctx),
        f"TASK: {m.task}",
        resolve(rt.instr.read("convergence", "action"), ctx),
    ]
    reply = _ask(rt, m, "\n\n".join(s for s in sections if s.strip()))
    m.final_output = functions.extract_finished_output(reply)
    if functions.has_tools(m.agent_type):
        _test_loop(rt, m, goal, reply)


def _test_loop(rt: Runtime, m: Member, goal: str, last_reply: str) -> None:
    for _ in range(_TEST_MAX_STEPS):
        ctx = _ctx(rt, m, goal)
        ans = _ask(rt, m, resolve(rt.instr.read("convergence", "test"), ctx))
        if _last_word_choice(ans, ("EXIT", "YES")) != "YES":
            return
        code_reply = _ask(rt, m, resolve(rt.instr.read("convergence", "test-confirm"), ctx))
        blocks = functions.extract_code_blocks(code_reply)
        if not blocks:
            output = "(no runnable code block was found)"
        else:
            # Functions may be split across several code blocks; run every block
            # that shares the first block's language, concatenated in order.
            lang = blocks[0][0]
            code = "\n\n".join(c for (l, c) in blocks if l == lang)
            rt.logbook.sandbox_run(m.label, lang)
            result = run_code(rt.executor, lang, code, rt.agent_dir(m.label))
            rt.logbook.sandbox_done(m.label, lang, result)
            output = format_result(result)
        ctx.shell_output = output
        _ask(rt, m, "Here is the output of running your code:\n>>RETURN_OUTPUT<<"
             .replace(">>RETURN_OUTPUT<<", functions.return_output(ctx)))
        if _last_word_choice(code_reply, ("EXIT",)) == "EXIT":
            return


def _convene_and_vote(rt: Runtime, members: list[Member], goal: str) -> list[dict]:
    records = []
    for m in members:
        rhetoric = [(o.agent_type, o.final_output) for o in members if o is not m]
        ctx = _ctx(rt, m, goal, rhetoric=rhetoric)
        reply = _ask(rt, m, resolve(rt.instr.read("convergence", "convene"), ctx))
        vote = parse_vote(reply)
        retries = 0
        while vote is None and retries < _RETRY:
            reply = _ask(rt, m, MALFORMED_REPLY + "\n" + resolve(">>CONVERGENCE_VOTE<<", ctx))
            vote = parse_vote(reply)
            retries += 1
        m.vote = vote if vote is not None else INCOMPLETE
        records.append({"agent_id": m.id, "agent_type": m.agent_type, "vote": m.vote})
    return records


def _reinitiate(rt: Runtime, members: list[Member], goal: str, spawn_subcouncil) -> None:
    for m in members:
        ctx = _ctx(rt, m, goal)
        # Vote-failed consolidation: the member reassesses / plans (no choice).
        _ask(rt, m, resolve(rt.instr.read("convergence", "vote-failed"), ctx))
        # Reinitiate: WAIT for the next vote, or CONTINUE working.
        choice = _required_choice(rt, m, resolve(rt.instr.read("convergence", "reinitiate"), ctx),
                                  ("WAIT", "CONTINUE"))
        if choice == "WAIT":
            m.waiting = True
            continue
        m.waiting = False
        # CONTINUE: redo the action (AGENT_INPUT) — this turn IS kept in history.
        action_reply = _ask(rt, m, resolve(rt.instr.read("convergence", "action"), ctx))
        m.final_output = functions.extract_finished_output(action_reply)
        # EXPANSION is a QUERY: ephemeral, not kept in the member's history.
        expansion = _query_choice(rt, m, resolve(rt.instr.read("queries", "expansion"), ctx),
                                  ("CONTINUE", "SPAWN"))
        if expansion == "SPAWN" and spawn_subcouncil:
            sub = spawn_subcouncil(m)
            if sub:
                m.final_output = sub
                # The member's AGENT_INPUT BECOMES the spawned council's output:
                # replace the last assistant turn so its history reads as its own.
                if m.messages and m.messages[-1]["role"] == "assistant":
                    m.messages[-1]["content"] = sub
                else:
                    m.messages.append({"role": "assistant", "content": sub})
                if m.log_path is not None:
                    rt.write_transcript(m.log_path, m.label, m.messages)


def run_convergence(rt: Runtime, members: list[Member], inherited: list[dict] | None,
                    inherited_goal: str, council_id: str, *, council_dir=None,
                    max_rounds: int | None = None, spawn_subcouncil=None) -> ConvergenceResult:
    """Drive ``members`` through the convergence loop. Always returns FINISHED;
    a non-unanimous round repeats until unanimity or the safety bound."""
    if not members:
        return ConvergenceResult(council_id, inherited_goal, "FINISHED", 0, [])

    safety = max_rounds if max_rounds is not None else (
        rt.settings.get_int("CONVERGENCE_MAX_ROUNDS", 6) or 6)

    for m in members:
        rt.logbook.agent_started(m.agent_type, m.task_truncated)
        _initiation(rt, m, inherited_goal, inherited)

    rnd = 0
    while True:
        rnd += 1
        records = _convene_and_vote(rt, members, inherited_goal)
        tally = tally_votes([r["vote"] for r in records])
        rt.logbook.log_vote_round(council_id, inherited_goal, rnd, records, tally)
        if council_dir is not None:
            rt.append_vote_log(council_dir, rnd, records, tally)

        if tally.unanimous_finished:
            for m in members:
                rt.logbook.agent_finished(m.agent_type, m.task_truncated)
            return ConvergenceResult(council_id, inherited_goal, "FINISHED", rnd, members)

        if rnd >= safety:
            return ConvergenceResult(council_id, inherited_goal, "FINISHED", rnd,
                                     members, force_resolved=True)

        _reinitiate(rt, members, inherited_goal, spawn_subcouncil)
