"""The primary agent: the plan-setter at the top of the swarm.

Its purpose is to take in a goal, talk it through, form a plan, and ask the user
whether to begin. Its tools are: ask questions, make a plan, and spawn agents.
It runs its own loop:

  1. The user sends a message; the primary replies, asking questions and shaping
     the plan, until it believes it has a grasp of the goal (it ends a message
     with ``<<READY>>``).
  2. The primary then asks the hard-coded question
     "Would you like me to spawn agents to complete this task?".
  3. If the user's answer parses as yes, the primary runs the SPAWNING query and
     hands the resulting directives to a council; the council's zipped FINISHED
     OUTPUT is returned. Otherwise it keeps planning.
"""
from __future__ import annotations

import re

from .council import parse_directives, run_council
from .runtime import Runtime
from .substitution import Context, resolve
from .voting import MALFORMED_REPLY

SPAWN_QUESTION = "Would you like me to spawn agents to complete this task?"
READY_TOKEN = "<<READY>>"

# A runtime directive appended to the primary's system prompt (we do not edit the
# author's instruction file). It defines the readiness signal Python watches for.
_READY_DIRECTIVE = (
    "When — and only when — you believe you have a sufficient grasp of the goal "
    "to begin work, end your message with the token " + READY_TOKEN + " on its own "
    "line. Until then, keep asking questions and shaping the plan.")

_YES = re.compile(r"\b(yes|yeah|yep|yup|sure|ok|okay|affirmative|do it|go ahead|please do|proceed)\b",
                  re.IGNORECASE)
_NO = re.compile(r"\b(no|nope|not yet|don'?t|stop|wait|hold on|cancel)\b", re.IGNORECASE)


def parse_yes(text: str) -> bool | None:
    """True/False for an affirmative/negative answer, or None if unparseable."""
    has_yes = bool(_YES.search(text or ""))
    has_no = bool(_NO.search(text or ""))
    if has_yes and not has_no:
        return True
    if has_no and not has_yes:
        return False
    return None


class PrimaryAgent:
    CHATTING = "chatting"
    AWAITING_CONFIRM = "awaiting_confirm"

    def __init__(self, rt: Runtime):
        self.rt = rt
        self.state = self.CHATTING
        self.messages: list[dict] = [{
            "role": "system",
            "content": rt.instr.system() + "\n\n"
            + rt.instr.read("primary", "agent") + "\n\n" + _READY_DIRECTIVE,
        }]
        self.goal = ""

    # ----- helpers -----
    def _chat(self, user_text: str) -> str:
        self.messages.append({"role": "user", "content": user_text})
        reply = self.rt.model.chat("primary", self.messages)
        self.messages.append({"role": "assistant", "content": reply})
        return reply

    def _ask_query(self, prompt: str) -> str:
        """Ask a QUERY turn without persisting it — queries are ephemeral; only
        the result they return is kept in the conversation (spec)."""
        return self.rt.model.chat("primary", self.messages + [{"role": "user", "content": prompt}])

    def _spawn(self) -> str:
        ctx = Context(instr=self.rt.instr, inherited_goal=self.goal)
        prompt = resolve(">>SPAWNING<<", ctx)
        directive_text = self._ask_query(prompt)
        members = parse_directives(self.rt, directive_text)
        retries = 0
        while not members and retries < 2:
            directive_text = self._ask_query(MALFORMED_REPLY + "\n" + prompt)
            members = parse_directives(self.rt, directive_text)
            retries += 1
        self.state = self.CHATTING
        if not members:
            return ("I couldn't turn that into a valid set of agent directives. "
                    "Let's refine the plan.")
        result = run_council(self.rt, members, list(self.messages), self.goal)
        # The council's output is inserted into the primary's memory as the
        # primary's own contribution, so the conversation can continue fluidly.
        self.messages.append({"role": "assistant", "content": result})
        return result

    # ----- main entry -----
    def send(self, user_text: str) -> str:
        """Feed a user message and return the primary's reply (or the swarm's
        final output once it spawns)."""
        if self.state == self.AWAITING_CONFIRM:
            answer = parse_yes(user_text)
            if answer is None:
                return MALFORMED_REPLY + "\n" + SPAWN_QUESTION
            if answer:
                return self._spawn()
            self.state = self.CHATTING
            return self._chat(user_text)

        reply = self._chat(user_text)
        if READY_TOKEN in reply:
            self.goal = reply.replace(READY_TOKEN, "").strip()
            self.state = self.AWAITING_CONFIRM
            return self.goal + "\n\n" + SPAWN_QUESTION
        return reply
