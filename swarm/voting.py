"""Vote parsing, tallying and the FINISHED/INCOMPLETE verdict."""
from __future__ import annotations

import re
from dataclasses import dataclass

FINISHED = "finished"
INCOMPLETE = "incomplete"

# Hard-coded replies for when a required response can't be parsed. Each scenario
# gets its own reminder that emphasizes the exact format expected there.
MALFORMED_REPLY = ("I'm sorry I didn't catch that, please follow the "
                   "aforementioned format.")


def malformed_choice(*options: str) -> str:
    """Reminder for a required one-of choice (WAIT/CONTINUE, YES/NO, ...)."""
    opts = " or ".join(options)
    return ("I'm sorry, I didn't catch that. Your reply must end with exactly "
            f"one of these words: {opts}.")


VOTE_REMINDER = (
    "I'm sorry, I didn't catch your vote. End your reply with exactly "
    "'I vote FINISHED' or 'I vote INCOMPLETE' as the final words, and nothing after.")

SPAWN_REMINDER = (
    "I'm sorry, I couldn't read the agent list. List each agent on its own line in "
    "exactly this layout:\nAGENT_TYPE: TASK: explanation\nAGENT_TYPE must be one of "
    "the agent types provided, TASK must be four words or fewer, and the expanded "
    "explanation follows the second colon. Output only those lines, nothing else.")

ZIPPER_COMMAND_REMINDER = (
    "I'm sorry, I didn't catch a valid command. Respond only with RETAIN <AGENT_NAME> "
    "or INSERT ... commands, one per line, in the order the final document should read.")

_VOTE_RE = re.compile(r"i\s+vote\s+(finished|incomplete)", re.IGNORECASE)


def parse_vote(text: str) -> str | None:
    """Return ``finished`` / ``incomplete`` from a vote message, or ``None`` if
    neither is present. The vote should be the final word, so if both appear the
    last one wins."""
    matches = _VOTE_RE.findall(text or "")
    if not matches:
        return None
    return matches[-1].lower()


@dataclass
class Tally:
    yay: int          # FINISHED votes
    nay: int          # INCOMPLETE votes

    @property
    def unanimous_finished(self) -> bool:
        return self.yay > 0 and self.nay == 0

    @property
    def status(self) -> str:
        return "FINISHED" if self.unanimous_finished else "INCOMPLETE"

    @property
    def pattern(self) -> str:
        """The ``X-X`` YAY-NAY pattern, e.g. ``4-5``."""
        return f"{self.yay}-{self.nay}"


def tally_votes(votes: list[str | None]) -> Tally:
    yay = sum(1 for v in votes if v == FINISHED)
    nay = sum(1 for v in votes if v != FINISHED)   # INCOMPLETE or unparsed
    return Tally(yay=yay, nay=nay)
