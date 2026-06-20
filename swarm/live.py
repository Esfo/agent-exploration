"""A pinned bottom status region for the terminal.

The most recent model generation (or whatever is running) streams into a small
buffer pinned at the bottom of the screen, while ordinary one-line notices scroll
above it. Pure ANSI / stdlib. When stdout isn't a TTY (pipes, tests) it degrades
to plain ``print`` so nothing changes for non-interactive use.

Invariant: between operations the cursor is parked at the top-left of the status
block (i.e. right after the last scrolled line). ``log`` clears the block, writes
a durable scroll line, then redraws the block below; ``feed`` just redraws.
"""
from __future__ import annotations

import shutil
import sys


class Live:
    def __init__(self, height: int = 3, enabled: bool = True):
        self.height = max(1, height)
        self.enabled = enabled and sys.stdout.isatty()
        self.buf = ""
        self.drawn = 0
        self.last_line = ""

    # ----- internals -----
    def _width(self) -> int:
        try:
            return max(20, shutil.get_terminal_size().columns)
        except Exception:  # noqa: BLE001
            return 80

    def _tail_lines(self) -> list[str]:
        if not self.buf:
            return []
        w = self._width()
        lines: list[str] = []
        for raw in self.buf.replace("\t", "    ").split("\n"):
            if raw == "":
                lines.append("")
                continue
            while len(raw) > w:
                lines.append(raw[:w])
                raw = raw[w:]
            lines.append(raw)
        return lines[-self.height:]

    def _render(self, lines: list[str]) -> None:
        # Cursor is at the status block top. Clear from here down, draw the
        # (dimmed) status lines, then park the cursor back at the top.
        out = ["\x1b[J"]
        for i, ln in enumerate(lines):
            out.append("\x1b[2m" + ln + "\x1b[0m")
            if i < len(lines) - 1:
                out.append("\n")
        if lines:
            out.append("\r")
            if len(lines) > 1:
                out.append(f"\x1b[{len(lines) - 1}A")
        sys.stdout.write("".join(out))
        sys.stdout.flush()
        self.drawn = len(lines)

    # ----- public -----
    def log(self, line) -> None:
        """Emit a durable line above the status block."""
        if not self.enabled:
            print(line)
            return
        for ln in str(line).split("\n"):
            sys.stdout.write("\x1b[J")     # clear current status block
            sys.stdout.write(ln + "\n")    # durable scroll line; cursor -> new top
            self.last_line = ln
            self._render(self._tail_lines())

    def append_last(self, suffix: str) -> None:
        """Tack ``suffix`` onto the last durable line, in place."""
        if not self.enabled:
            print(suffix.strip())
            return
        self.last_line += suffix
        sys.stdout.write("\x1b[J")            # clear status block
        sys.stdout.write("\x1b[1A\r\x1b[2K")  # up to the last scroll line, clear it
        sys.stdout.write(self.last_line + "\n")
        self._render(self._tail_lines())

    def begin(self) -> None:
        """Start a fresh generation in the buffer."""
        self.buf = ""
        if self.enabled:
            self._render([])

    def feed(self, delta: str) -> None:
        """Append streamed text to the buffer and redraw it."""
        if not self.enabled:
            return
        self.buf += delta
        self._render(self._tail_lines())

    def finish(self) -> None:
        """Clear the buffer region (e.g. before committing durable output)."""
        self.buf = ""
        if self.enabled:
            sys.stdout.write("\x1b[J")
            sys.stdout.flush()
            self.drawn = 0
