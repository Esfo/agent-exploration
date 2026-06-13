"""Token budgeting (spec section 12).

No tokenizer dependency: uses a chars/token heuristic (~3.5 chars/token is a
safe overestimate for code-heavy English). The point is to refuse to send a
prompt that cannot leave room for the reserved output, not to be exact.
"""
from __future__ import annotations

CHARS_PER_TOKEN = 3.5


class ContextLimitReached(Exception):
    pass


def estimate_tokens(text: str) -> int:
    return int(len(text) / CHARS_PER_TOKEN) + 1


def estimate_messages(messages: list[dict]) -> int:
    return sum(estimate_tokens(m.get("content", "")) + 4 for m in messages)


def safe_input_budget(num_ctx: int, num_predict: int, safety_margin: int) -> int:
    return max(0, num_ctx - num_predict - safety_margin)


def ensure_fits(messages: list[dict], num_ctx: int, num_predict: int,
                safety_margin: int) -> int:
    """Return estimated input tokens, or raise ContextLimitReached."""
    budget = safe_input_budget(num_ctx, num_predict, safety_margin)
    used = estimate_messages(messages)
    if used > budget:
        raise ContextLimitReached(
            f"estimated input {used} tokens exceeds budget {budget} "
            f"(num_ctx={num_ctx}, num_predict={num_predict}, margin={safety_margin})"
        )
    return used
