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


def _summarize_dropped(dropped: list[dict], max_summary_tokens: int) -> str:
    """Condense dropped middle messages into one short recap."""
    limit = int(max_summary_tokens * CHARS_PER_TOKEN)
    parts = []
    for m in dropped:
        snippet = " ".join(m.get("content", "").split())
        parts.append(f"[{m.get('role','?')}] {snippet}")
    recap = " | ".join(parts)
    if len(recap) > limit:
        recap = recap[:limit] + " …"
    return f"[earlier context summarized — {len(dropped)} message(s) omitted]\n{recap}"


def summarize_to_fit(messages: list[dict], num_ctx: int, num_predict: int,
                     safety_margin: int, max_summary_tokens: int) -> list[dict]:
    """Trim history to fit the budget (spec section 12).

    Always keeps the system prompt and the context packet (messages[0:2]) plus a
    tail of the most recent turns; the dropped middle is replaced by one summary
    message. Raises ContextLimitReached only if even the minimal head doesn't fit.
    """
    budget = safe_input_budget(num_ctx, num_predict, safety_margin)
    if estimate_messages(messages) <= budget:
        return messages

    head = messages[:2]
    tail_source = messages[2:]
    head_cost = estimate_messages(head)
    summary_reserve = max_summary_tokens + 8
    if head_cost + summary_reserve > budget:
        # Even head + a summary won't fit; head alone must at least fit.
        if head_cost > budget:
            raise ContextLimitReached(
                f"context packet alone ({head_cost} tokens) exceeds budget {budget}")
        return head

    # Greedily keep the most recent messages that fit alongside head + summary.
    kept_tail: list[dict] = []
    running = head_cost + summary_reserve
    for m in reversed(tail_source):
        c = estimate_tokens(m.get("content", "")) + 4
        if running + c > budget:
            break
        kept_tail.insert(0, m)
        running += c

    dropped = tail_source[: len(tail_source) - len(kept_tail)]
    if not dropped:
        return messages  # nothing to drop; shouldn't happen given the over-budget check
    summary = {"role": "user", "content": _summarize_dropped(dropped, max_summary_tokens)}
    return head + [summary] + kept_tail
