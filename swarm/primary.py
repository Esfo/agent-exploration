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


def _parse_yes_no(text: str) -> bool | None:
    """True/False from a confirm verdict (last YES/NO wins), or None if neither
    token is present."""
    upper = (text or "").upper()
    yes, no = upper.rfind("YES"), upper.rfind("NO")
    if yes < 0 and no < 0:
        return None
    return yes > no


def _ends_yes(text: str) -> bool:
    return bool(_parse_yes_no(text))


class PrimaryAgent:
    def __init__(self, rt: Runtime, on_token=None):
        self.rt = rt
        self.on_token = on_token   # if set, visible replies stream chunk-by-chunk
        self.messages: list[dict] = [{
            "role": "system",
            "content": rt.instr.system() + "\n\n" + rt.instr.read("primary", "agent"),
        }]
        self.goal = ""
        self._council_count = 0

    # ----- turns -----
    def _chat(self, user_text: str) -> str:
        """A visible turn, kept in the primary's history (streamed if enabled)."""
        self.messages.append({"role": "user", "content": user_text})
        if self.on_token is not None:
            reply = self.rt.model.chat_stream("primary", self.messages, self.on_token)
        else:
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

    # ----- the goal the council inherits -----
    def _derive_goal(self) -> str:
        """Ask the primary, behind the scenes, to state the actual task as one
        sentence — so the council's inherited goal reflects the conversation, not
        whatever the first message happened to be. Ephemeral and invisible."""
        ctx = Context(instr=self.rt.instr)
        reply = self._ask_query(resolve(self.rt.instr.read("primary", "goal"), ctx))
        for line in (reply or "").splitlines():
            if line.strip():
                return line.strip()
        # Fallback: the most recent real user message.
        return next((m["content"].strip() for m in reversed(self.messages)
                     if m["role"] == "user"), "").strip()

    # ----- the hidden confirm check -----
    def _confirm(self) -> bool:
        """Ask the primary, behind the scenes, whether the user has agreed to
        spawn. The dialogue is invisible and forgotten; only YES/NO is read. If
        the verdict isn't a clear YES/NO, re-ask with the malformed-input reply;
        an unresolved verdict defaults to NO (don't spawn)."""
        ctx = Context(instr=self.rt.instr, inherited_goal=self.goal)
        prompt = resolve(self.rt.instr.read("primary", "confirm"), ctx)
        verdict = self._ask_query(prompt)
        decision = _parse_yes_no(verdict)
        tries = 0
        while decision is None and tries < 2:
            verdict = self._ask_query(MALFORMED_REPLY + "\n" + prompt)
            decision = _parse_yes_no(verdict)
            tries += 1
        return bool(decision)

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
        self._council_count += 1
        label = str(self._council_count)   # top-level councils: 1, 2, 3, ...
        council_dir = self.rt.primary_dir / "councils" / f"council_{label}"
        result = run_council(self.rt, members, list(self.messages), self.goal,
                             council_dir, label)
        # Only the council's RESULT (never its conversation) enters the primary's
        # memory, as the primary's own contribution; it is also saved to the
        # results library.
        self.messages.append({"role": "assistant", "content": result})
        self._write_log()
        path = self.rt.save_result(self.goal, result)
        self.rt.logbook.chat(f"result saved to {path}")
        if self.on_token is not None:   # the result wasn't streamed; show it now
            self.on_token("\n\n" + result + "\n")
        return result

    # ----- main entry -----
    def run_once(self, user_text: str) -> str:
        """Skip the planning/confirm dialogue: derive the goal from the prompt and
        spawn a council on it immediately. Used by --oneprompt."""
        self.messages.append({"role": "user", "content": user_text})
        self._write_log()
        self.goal = self._derive_goal()
        return self._spawn()

    def send(self, user_text: str) -> str:
        """Feed a user message; return the primary's reply, or (once the hidden
        confirm verdict is YES) the reply followed by the swarm's result."""
        reply = self._chat(user_text)
        if self._confirm():
            self.goal = self._derive_goal()
            return reply + "\n\n" + self._spawn()
        return reply
