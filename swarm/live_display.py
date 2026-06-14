"""Live terminal display: one updating line per active agent.

Active agents occupy a live region at the bottom of the terminal; each agent has
exactly ONE line that updates in place (started → in progress → finished) instead
of scrolling new blocks. When an agent finishes, its final line is scrolled up as
a permanent line and removed from the live region. Other output (swarm summaries,
command results) also scrolls above the live region so nothing jumps around.

Only active on a real TTY; otherwise it's a no-op (the caller logs to JSONL/DB
regardless).
"""
from __future__ import annotations

import sys
import threading


class LiveDisplay:
    def __init__(self, enabled: bool = True, stream=None):
        self.stream = stream or sys.stdout
        self.enabled = bool(enabled) and hasattr(self.stream, "isatty") and self.stream.isatty()
        self.lock = threading.RLock()
        self.active: dict[str, str] = {}   # agent_id -> current line (insertion-ordered)
        self.rendered = 0

    def _w(self, s: str) -> None:
        self.stream.write(s)
        self.stream.flush()

    def _clear_region(self) -> None:
        if self.rendered:
            self._w(f"\033[{self.rendered}A\033[J")  # cursor up N, clear to end of screen
        self.rendered = 0

    def _draw_region(self) -> None:
        for text in self.active.values():
            self._w("\r\033[2K" + text + "\n")
        self.rendered = len(self.active)

    def update(self, agent_id: str, text: str) -> None:
        if not self.enabled:
            return
        with self.lock:
            self._clear_region()
            self.active[agent_id] = text
            self._draw_region()

    def finish(self, agent_id: str, final_text: str) -> None:
        if not self.enabled:
            return
        with self.lock:
            self._clear_region()
            self.active.pop(agent_id, None)
            self._w("\r\033[2K" + final_text + "\n")  # permanent, scrolls above region
            self._draw_region()

    def permanent(self, text: str) -> None:
        """Print a line/block that scrolls above the live region."""
        if not self.enabled:
            return
        with self.lock:
            self._clear_region()
            for line in str(text).split("\n"):
                self._w("\r\033[2K" + line + "\n")
            self._draw_region()
