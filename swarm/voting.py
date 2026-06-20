"""Vote parsing, tallying and the FINISHED/INCOMPLETE verdict."""
from __future__ import annotations

import re
from dataclasses import dataclass

FINISHED = "finished"
INCOMPLETE = "incomplete"

# Hard-coded reply whenever a required response can't be parsed (vote, spawn,
# expansion, ...). The same line is reused everywhere a format is expected.
MALFORMED_REPLY = ("I'm sorry I didn't catch that, please follow the "
                   "aforementioned format.")

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
