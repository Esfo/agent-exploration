"""Summarize-on-overflow: top-down context compression.

When an agent's conversation grows past its context budget, the oldest turns are
compressed into a single briefing and the most recent turns are kept verbatim,
so the latest context is retained as fully as possible while space is freed for
the conversation to continue. This runs transparently before every model call
and mutates the agent's history in place, so the saving persists going forward.
"""
from __future__ import annotations

SUMMARY_HEADER = "[SUMMARY OF EARLIER CONVERSATION]"
SUMMARY_PROMPT = (
    "Summarize the earlier conversation below concisely, preserving the goal, the "
    "decisions made, any code or concrete output produced, and the facts needed to "
    "continue. Write a dense briefing, not a transcript.\n\nCONVERSATION:\n")

_CHARS_PER_TOKEN = 4   # rough estimate; we only need an order-of-magnitude guard


class Summarizer:
    def __init__(self, model):
        self.model = model
        self.s = model.s

    def _size(self, messages) -> int:
        return sum(len(m.get("content", "")) for m in messages)

    def _budget_chars(self, role: str) -> int:
        opts = self.model._options(role)
        margin = self.s.get_int("TOKEN_SAFETY_MARGIN", 256) or 256
        tokens = max(1024, opts["num_ctx"] - opts["num_predict"] - margin)
        return tokens * _CHARS_PER_TOKEN

    def fit(self, role: str, messages: list[dict]) -> None:
        """Compress ``messages`` in place if they exceed the role's budget."""
        if not self.s.get_bool("SUMMARIZE_ON_OVERFLOW", True):
            return
        if len(messages) < 4:
            return
        budget = self._budget_chars(role)
        if self._size(messages) <= budget:
            return
        frac = self.s.get_float("SUMMARIZE_RECENT_FRACTION", 0.5) or 0.5
        keep_budget = budget * frac

        # Keep the most recent messages that fit in keep_budget; summarize the
        # rest (top-down). Always leave at least one message to summarize.
        tail: list[dict] = []
        acc = 0
        for m in reversed(messages):
            if acc >= keep_budget and len(tail) < len(messages) - 1:
                break
            tail.insert(0, m)
            acc += len(m.get("content", ""))
        head = messages[:len(messages) - len(tail)]
        if not head:
            return
        summary = self._summarize(self._summarize_role(role), head)
        messages[:] = [{"role": "user", "content": SUMMARY_HEADER + "\n" + summary}] + tail

    def _summarize_role(self, role: str) -> str:
        # Use the dedicated summarizer config if present, else the agent's own.
        return "summarizer" if self.s.get(f"DEFAULT_SUMMARIZER_MODEL") else role

    def _summarize(self, role: str, head: list[dict]) -> str:
        text = "\n\n".join(f"[{m.get('role')}] {m.get('content', '')}" for m in head)
        try:
            resp = self.model.client.chat(
                endpoint=self.model._endpoint(role),
                model=self.model._model_name(role),
                messages=[{"role": "user", "content": SUMMARY_PROMPT + text}],
                options=self.model._options(role))
            out = (resp.content or "").strip()
            if out:
                return out
        except Exception:  # noqa: BLE001 - summarization must never break the loop
            pass
        # Deterministic fallback so a spawn/turn never fails on a model error.
        lines = []
        for m in head:
            first = (m.get("content", "").strip().splitlines() or [""])[0]
            lines.append(f"- {m.get('role')}: {first[:120]}")
        return "\n".join(lines)
