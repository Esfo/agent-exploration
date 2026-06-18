"""The convergence process: a group of spawned agents hold a round-based group
conversation and vote until they unanimously agree the work is FINISHED.

This is what happens every time a group of agents is spawned together. Each agent
inherits the same conversation (the shared INPUT) but carries its own PURPOSE
(its AGENT_TYPE angle). Per round:

  1. Response phase — every agent produces a response (a plan or an execution).
     All responses are aggregated and fed back into every agent.
  2. Vote phase — every agent makes an articulate assessment and ends with exactly
     "I vote FINISHED" or "I vote INCOMPLETE". Votes are collected by simple text
     match (the vote must be the final word).

If every agent votes FINISHED, convergence is complete and the result is handed
off to the zipper process. If any agent votes INCOMPLETE, the collective reasoning
is consolidated, fed back to every agent, and the vote round repeats — up to
CONVERGENCE_MAX_ROUNDS.

Prompt wording matches the master spec. Model calls are direct single-turn chats
(like the summarizer) so the loop is deterministic and bounded; richer per-agent
tool execution can be layered into the response phase later.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# ----- spec prompt wording -----

INITIATION = (
    "Don't be pushed around, stand your ground and only agree when it's reasonable "
    "to do so. Your job is to work together with the other agents to deliver a "
    "finished project."
)

RESPONSE_PROMPT = (
    "Please give the most appropriate response at this level of the project, "
    "either plan or execute."
)

VOTE_PROMPT = (
    "Has every aspect of this work met the standard intended by its creation?\n"
    "From your perspective, considering the {agent_type} angle of this project, and "
    "the {goal_type} of this project, would you vote to say this work is complete, "
    "or does it need more work?\n"
    "Please make an articulate assessment from your point of view as {agent_type}, "
    "then at the end of your argument vote either FINISHED or INCOMPLETE at the very "
    "end.\n"
    'Say "I vote FINISHED" or "I vote INCOMPLETE", do not say both of these '
    "together.\n"
    "Do not write anything after your vote, it should be the final word."
)

INCOMPLETE_FEEDBACK = (
    "The vote failed, here's the collective reasoning, please read this "
    "consolidation and respond appropriately with a reassessment from your "
    "perspective of {agent_type} regarding {goal_type}.\n"
    "Please articulate the priorities of each assessment offered here, and please "
    "articulate where your next assessment will stand with respect to the rest of "
    "the work being done.\n"
    "Please complete your work as {agent_type} for {goal_type} in attempting to "
    "bring this project to a close.\n\n"
    "COLLECTIVE REASONING:\n{reasoning}"
)

FINISHED = "finished"
INCOMPLETE = "incomplete"

_VOTE_RE = re.compile(r"i\s+vote\s+(finished|incomplete)", re.IGNORECASE)


def parse_vote(text: str) -> str | None:
    """Return 'finished' / 'incomplete' from an agent's vote message, or None.

    The vote is meant to be the final word, so if a message somehow contains both
    (against instruction), the LAST occurrence wins.
    """
    matches = _VOTE_RE.findall(text or "")
    if not matches:
        return None
    return matches[-1].lower()


@dataclass
class AgentVote:
    agent_id: str
    role: str
    vote: str | None          # FINISHED / INCOMPLETE / None (unparseable)
    reasoning: str            # the full vote message


@dataclass
class RoundResult:
    index: int
    responses: list[dict] = field(default_factory=list)   # {agent_id, role, response}
    votes: list[AgentVote] = field(default_factory=list)
    unanimous_finished: bool = False


@dataclass
class ConvergenceResult:
    finished: bool
    rounds: list[RoundResult]
    goal_type: str
    consolidation: str        # last round's aggregated responses (handoff payload)

    @property
    def round_count(self) -> int:
        return len(self.rounds)

    def as_dict(self) -> dict:
        return {
            "finished": self.finished,
            "rounds": self.round_count,
            "goal_type": self.goal_type,
            "consolidation": self.consolidation,
            "votes": [
                {"round": r.index,
                 "votes": [{"agent_id": v.agent_id, "role": v.role, "vote": v.vote}
                           for v in r.votes]}
                for r in self.rounds
            ],
        }


def _purpose(agent: dict, goal_type: str) -> str:
    role = agent.get("role", "agent")
    task = (agent.get("task") or "").strip()
    lines = [
        f"You are the {role} agent. Your AGENT_TYPE is {role}; the GOAL_TYPE of "
        f"this project is {goal_type}.",
        INITIATION,
    ]
    if task:
        lines.append(f"Your specific angle / task:\n{task}")
    return "\n\n".join(lines)


def _chat(ctx, agent: dict, messages: list[dict], *, temperature: float | None = None) -> str:
    """One direct chat turn for an agent (mirrors the summarizer's call path)."""
    opts = {
        "num_ctx": int(agent.get("num_ctx") or 8192),
        "num_predict": int(agent.get("num_predict") or 1024),
        "temperature": float(temperature if temperature is not None
                             else (agent.get("temperature") or 0.4)),
    }
    endpoint = agent.get("ollama_endpoint")
    model = agent.get("selected_model")
    if ctx.scheduler is not None:
        with ctx.scheduler.inference_slot(agent.get("execution_class", "cpu"), agent["id"]):
            resp = ctx.client.chat(endpoint=endpoint, model=model, messages=messages, options=opts)
    else:
        resp = ctx.client.chat(endpoint=endpoint, model=model, messages=messages, options=opts)
    try:
        ctx.db.save_model_call(agent["id"], resp.telemetry)
    except Exception:  # noqa: BLE001 - telemetry logging must never break the loop
        pass
    return (resp.content or "").strip()


def _aggregate_responses(responses: list[dict]) -> str:
    return "\n\n".join(
        f"[{r['role']} ({r['agent_id']})]\n{r['response']}".strip()
        for r in responses
    )


def _agent_program(ctx, agent):
    """Parse the agent's primary instruction file as an executable VERIFY program,
    or return None if it has none / isn't a program."""
    from .instruction_program import parse_program
    from .model_selector import ROLE_PRIMARY_FILE
    role = agent.get("role", "")
    entry = ROLE_PRIMARY_FILE.get(role)
    if not entry:
        return None
    rel = ctx.settings.get(entry[0])
    if not rel:
        return None
    path = ctx.settings.root / rel
    if not path.exists():
        return None
    prog = parse_program(path.read_text(encoding="utf-8"))
    return prog if prog.is_executable else None


def _program_vote(ctx, agent, shared, purpose):
    """Decide an agent's vote by executing its instruction program. The agent is
    framed by its program (PURPOSE + guidance) with INPUT: hard-substituted by the
    shared convergence context; each VERIFY question is asked of the model and
    reaching FINISH casts a FINISHED vote. Returns (vote, reasoning) or None if no
    program applies."""
    from .instruction_program import messages_to_text, run_program
    prog = _agent_program(ctx, agent)
    if prog is None:
        return None

    # Frame the agent with its program and the substituted INPUT (spec behavior).
    sys_text = prog.system_text() + "\n\n" + purpose
    input_text = prog.render_input(messages_to_text(shared))
    base = [{"role": "system", "content": sys_text}]
    if input_text:
        base.append({"role": "user", "content": "INPUT:\n" + input_text})

    asked: list[str] = []

    def ask(question: str) -> str:
        asked.append(question)
        msgs = base + [
            {"role": "user", "content": question
             + '\nAnswer with a short YES or NO and a brief reason.'},
        ]
        return _chat(ctx, agent, msgs)

    out = run_program(prog, ask, max_loops=ctx.settings.get_int("VERIFY_MAX_LOOPS", 6) or 6)
    vote = FINISHED if out.finished else INCOMPLETE
    reasoning = (f"[program vote via {len(asked)} verify step(s)] "
                 + " | ".join(f"{s.question}->{s.answer}" for s in out.log if s.kind == "verify"))
    return vote, reasoning


def _aggregate_reasoning(votes: list[AgentVote]) -> str:
    out = []
    for v in votes:
        tag = (v.vote or "no-vote").upper()
        out.append(f"[{v.role} ({v.agent_id}) — voted {tag}]\n{v.reasoning}".strip())
    return "\n\n".join(out)


def run_convergence(ctx, agents: list[dict], inherited: list[dict] | None,
                    goal_type: str, *, max_rounds: int | None = None) -> ConvergenceResult:
    """Drive a group of agents through response→vote rounds until unanimous
    FINISHED (or max_rounds). `agents` are already-created agent records; their
    role is the AGENT_TYPE. `inherited` is the shared branch conversation (INPUT).
    """
    if not agents:
        return ConvergenceResult(finished=True, rounds=[], goal_type=goal_type,
                                 consolidation="")

    if max_rounds is None:
        max_rounds = ctx.settings.get_int("CONVERGENCE_MAX_ROUNDS", 4) or 4

    shared: list[dict] = list(inherited or [])
    rounds: list[RoundResult] = []
    last_consolidation = ""

    for i in range(1, max_rounds + 1):
        rnd = RoundResult(index=i)

        # --- response phase: each agent plans or executes ---
        for agent in agents:
            purpose = _purpose(agent, goal_type)
            msgs = shared + [
                {"role": "system", "content": purpose},
                {"role": "user", "content": RESPONSE_PROMPT},
            ]
            response = _chat(ctx, agent, msgs)
            rnd.responses.append({"agent_id": agent["id"], "role": agent.get("role", "agent"),
                                  "response": response})

        consolidation = _aggregate_responses(rnd.responses)
        last_consolidation = consolidation
        # Feed every agent the aggregation before they vote.
        shared = shared + [{"role": "user",
                            "content": f"[CONVERGENCE round {i} — aggregated responses]\n"
                                       + consolidation}]

        # --- vote phase ---
        use_program = ctx.settings.get_bool("INSTRUCTION_PROGRAM_VOTING", True)
        for agent in agents:
            purpose = _purpose(agent, goal_type)
            pv = _program_vote(ctx, agent, shared, purpose) if use_program else None
            if pv is not None:
                vote, reasoning = pv
            else:
                vote_q = VOTE_PROMPT.format(agent_type=agent.get("role", "agent"),
                                            goal_type=goal_type)
                msgs = shared + [
                    {"role": "system", "content": purpose},
                    {"role": "user", "content": vote_q},
                ]
                reasoning = _chat(ctx, agent, msgs)
                vote = parse_vote(reasoning)
            rnd.votes.append(AgentVote(agent_id=agent["id"], role=agent.get("role", "agent"),
                                       vote=vote, reasoning=reasoning))

        _log_votes(ctx, agents, rnd)

        rnd.unanimous_finished = bool(rnd.votes) and all(v.vote == FINISHED for v in rnd.votes)
        rounds.append(rnd)

        if rnd.unanimous_finished:
            return ConvergenceResult(finished=True, rounds=rounds, goal_type=goal_type,
                                     consolidation=last_consolidation)

        # Not unanimous → consolidate reasoning, feed back, repeat the loop.
        reasoning_blob = _aggregate_reasoning(rnd.votes)
        feedback = INCOMPLETE_FEEDBACK.format(
            agent_type="each agent", goal_type=goal_type, reasoning=reasoning_blob)
        shared = shared + [{"role": "user", "content": feedback}]

    # Ran out of rounds without unanimity.
    return ConvergenceResult(finished=False, rounds=rounds, goal_type=goal_type,
                             consolidation=last_consolidation)


def _log_votes(ctx, agents, rnd: RoundResult) -> None:
    """Record each round's votes to logs + emit a one-line chat summary."""
    events = getattr(ctx, "events", None)
    swarm_id = (agents[0].get("swarm_id") if agents else None)
    tally = {}
    for v in rnd.votes:
        tally[v.vote or "no-vote"] = tally.get(v.vote or "no-vote", 0) + 1
    if events is not None:
        try:
            events._jsonl("convergence.jsonl", {
                "swarm_id": swarm_id, "round": rnd.index, "tally": tally,
                "votes": [{"agent_id": v.agent_id, "role": v.role, "vote": v.vote}
                          for v in rnd.votes],
            })
        except Exception:  # noqa: BLE001
            pass
        try:
            summary = ", ".join(f"{k.upper()}:{n}" for k, n in sorted(tally.items()))
            events.chat(f"convergence round {rnd.index} votes — {summary}")
        except Exception:  # noqa: BLE001
            pass
