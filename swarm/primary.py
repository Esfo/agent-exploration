"""The primary agent: the plan-setter at the top of the swarm.

Its purpose is to take in a goal, talk it through, form a plan, and ask the user
whether to begin. Its tools are: ask questions, make a plan, and spawn agents.

The loop is:

  1. The user sends a message; the primary replies (visible, kept in history),
     asking questions and shaping the plan in its own words.
  2. After every user turn, a *hidden* confirm query (``instructions/primary/
     confirm``) asks the primary itself whether the user has agreed to spawn a
     swarm. This query is never shown to the user and never kept in history
     (ephemeral); Python only reads its YES/NO verdict.
  3. On YES, the primary runs the SPAWNING query and hands the directives to a
     council; the council's result is returned and saved. On NO, planning
     continues.

There is no constant keyword check on the user's messages — the agent decides
readiness, Python only parses the verdict of the confirm prompt.
"""
from __future__ import annotations

from .council import parse_directives, run_council
from .runtime import Runtime
from .substitution import Context, resolve
from .voting import MALFORMED_REPLY


def _ends_yes(text: str) -> bool:
    """Whether the confirm verdict resolves to YES (last YES/NO wins)."""
    upper = (text or "").upper()
    yes, no = upper.rfind("YES"), upper.rfind("NO")
    return yes > no


class PrimaryAgent:
    def __init__(self, rt: Runtime):
        self.rt = rt
        self.messages: list[dict] = [{
            "role": "system",
            "content": rt.instr.system() + "\n\n" + rt.instr.read("primary", "agent"),
        }]
        self.goal = ""

    # ----- turns -----
    def _chat(self, user_text: str) -> str:
        """A visible turn, kept in the primary's history."""
        self.messages.append({"role": "user", "content": user_text})
        reply = self.rt.model.chat("primary", self.messages)
        self.messages.append({"role": "assistant", "content": reply})
        self._write_log()
        return reply

    def _write_log(self) -> None:
        self.rt.write_transcript(self.rt.primary_dir / "primary.txt", "primary", self.messages)

    def _ask_query(self, prompt: str) -> str:
        """A QUERY turn: asked with the current history as context but NOT kept —
        queries are ephemeral and invisible; only their result matters (spec)."""
        return self.rt.model.chat("primary", self.messages + [{"role": "user", "content": prompt}])

    # ----- the hidden confirm check -----
    def _confirm(self) -> bool:
        """Ask the primary, behind the scenes, whether the user has agreed to
        spawn. The dialogue is invisible and forgotten; only YES/NO is read."""
        ctx = Context(instr=self.rt.instr, inherited_goal=self.goal)
        verdict = self._ask_query(resolve(self.rt.instr.read("primary", "confirm"), ctx))
        return _ends_yes(verdict)

    # ----- spawning -----
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
        if not members:
            return ("I couldn't turn that into a valid set of agent directives. "
                    "Let's refine the plan.")
        council_dir = self.rt.next_council_dir(self.rt.primary_dir / "councils")
        result = run_council(self.rt, members, list(self.messages), self.goal, council_dir)
        # Only the council's RESULT (never its conversation) enters the primary's
        # memory, as the primary's own contribution; it is also saved to the
        # results library.
        self.messages.append({"role": "assistant", "content": result})
        self._write_log()
        path = self.rt.save_result(self.goal, result)
        self.rt.logbook.chat(f"result saved to {path}")
        return result

    # ----- main entry -----
    def send(self, user_text: str) -> str:
        """Feed a user message; return the primary's reply, or (once the hidden
        confirm verdict is YES) the reply followed by the swarm's result."""
        if not self.goal:
            self.goal = user_text.strip()
        reply = self._chat(user_text)
        if self._confirm():
            return reply + "\n\n" + self._spawn()
        return reply
