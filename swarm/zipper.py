"""The zipper process.

After a council converges FINISHED, the zipper reduction agent assembles the
members' final outputs into one delivered product. It writes nothing itself: it
issues commands that Python applies to a document built from the existing final
outputs, then confirms the result and sends it upstream with a ``FINISHED
OUTPUT`` header.

The zipper inherits the conversation that brought the council about, but none of
the council's internal conversation — only the members' final outputs. It gets
no system instruction (the system prompt is given to every role except the
zipper).

Commands (one per line, spoken in final-document order)::

    RETAIN <AGENT_NAME>                       keep that agent's whole output
    INSERT <AGENT_NAME> line X to Y [PREPEND <mark>]
    INSERT <AGENT_NAME> line X [PREPEND <mark>]
    INSERT TEXT <literal>                      append a literal line (e.g. ```)
"""
from __future__ import annotations

import re

from . import ids
from .functions import FINISHED_MARKER
from .runtime import Runtime
from .substitution import Context, resolve

_RETAIN = re.compile(r"^\s*RETAIN\s+(.+?)\s*$", re.IGNORECASE)
# INSERT line N <literal>  -> positional insert into the DOCUMENT at line N.
_INSERT_POS = re.compile(r"^\s*INSERT\s+line\s+(\d+)\s?(.*)$", re.IGNORECASE)
# INSERT <agent> line X [to Y] [PREPEND mark] -> append source lines X..Y.
_INSERT_SRC = re.compile(
    r"^\s*INSERT\s+(.+?)\s+line\s+(\d+)(?:\s+to\s+(\d+))?\s*(?:PREPEND\s+(.*))?$",
    re.IGNORECASE)
_INSERT_TEXT = re.compile(r"^\s*INSERT\s+TEXT\s+(.*)$", re.IGNORECASE)
_ZIPPER_MAX_LOOPS = 4


class Document:
    """Assembles a final document from labelled source outputs.

    ``RETAIN`` and source-range ``INSERT`` append to the document in command
    order. ``INSERT line N <text>`` inserts a literal line at *document*
    position N, bumping the existing lines down (auto-renumbered): inserting
    twice at line N leaves the first insertion at line N+1, exactly as the
    zipper instructions describe (``list.insert`` semantics).
    """

    def __init__(self, final_outputs: list[tuple[str, str]]):
        self.sources = {name: (text or "").splitlines() for name, text in final_outputs}
        self.out: list[str] = []

    def render(self) -> str:
        return "\n".join(self.out)

    def _resolve(self, name: str) -> str | None:
        name = name.strip()
        if name in self.sources:
            return name
        for key in self.sources:
            if name.lower() in key.lower() or key.lower().startswith(name.lower()):
                return key
        return None

    def retain(self, name: str) -> None:
        key = self._resolve(name)
        if key is not None:
            self.out.extend(self.sources[key])

    def insert_source(self, name: str, start: int, end: int | None, prepend: str) -> None:
        key = self._resolve(name)
        if key is None:
            return
        lines = self.sources[key]
        end = end if end is not None else start
        for ln in lines[max(start - 1, 0):end]:
            self.out.append(f"{prepend}{ln}" if prepend else ln)

    def insert_at(self, line_no: int, text: str) -> None:
        """Insert a literal line at document position ``line_no`` (1-indexed),
        bumping later lines down. Out-of-range positions clamp to the ends."""
        idx = max(0, min(line_no - 1, len(self.out)))
        self.out.insert(idx, text)

    def insert_text(self, text: str) -> None:
        self.out.append(text)

    def apply(self, response: str) -> int:
        """Apply every command line in ``response``. Returns commands applied."""
        applied = 0
        for raw in (response or "").splitlines():
            mt = _INSERT_TEXT.match(raw)
            if mt:
                self.insert_text(mt.group(1)); applied += 1; continue
            mp = _INSERT_POS.match(raw)
            if mp:
                self.insert_at(int(mp.group(1)), mp.group(2)); applied += 1; continue
            ms = _INSERT_SRC.match(raw)
            if ms:
                name, x, y, prepend = ms.groups()
                self.insert_source(name, int(x), int(y) if y else None, prepend or "")
                applied += 1; continue
            mk = _RETAIN.match(raw)
            if mk:
                self.retain(mk.group(1)); applied += 1; continue
        return applied


def run_zipper(rt: Runtime, final_outputs: list[tuple[str, str]],
               inherited: list[dict] | None, *, council_dir=None, task: str = "",
               task_truncated: str = "") -> str:
    """Run the zipper workflow and return the upstream payload (prefixed with
    ``FINISHED OUTPUT``)."""
    zid = ids.next_id("zipper")
    log_path = (council_dir / f"{zid}.txt") if council_dir is not None else None
    ctx = Context(instr=rt.instr, task=task, task_truncated=task_truncated,
                  final_outputs=final_outputs)
    messages: list[dict] = list(inherited or [])
    initiation = resolve(rt.instr.read("zipper", "initiate"), ctx)
    final_block = resolve(">>FINAL_OUTPUT<<", ctx)
    messages.append({"role": "user", "content": initiation + "\n\n" + final_block})

    doc = Document(final_outputs)
    for _ in range(_ZIPPER_MAX_LOOPS):
        reply = rt.model.chat("zipper", messages)
        messages.append({"role": "assistant", "content": reply})
        doc.apply(reply)
        ctx.document = doc.render()
        finish_prompt = resolve(rt.instr.read("zipper", "finish"), ctx)
        messages.append({"role": "user", "content": finish_prompt})
        verdict = rt.model.chat("zipper", messages)
        messages.append({"role": "assistant", "content": verdict})
        if log_path is not None:
            rt.write_transcript(log_path, f"zipper ({zid})", messages)
        if _last_word(verdict) == "CONFIRM":
            break

    body = doc.render().strip()
    if not body:   # zipper produced nothing usable: fall back to raw outputs
        body = "\n\n".join(f"{name}\n{text}".strip() for name, text in final_outputs)
    return f"{FINISHED_MARKER}\n{body}"


def _last_word(text: str) -> str | None:
    upper = (text or "").upper()
    c, p = None, -1
    for opt in ("CONFIRM", "CONTINUE"):
        pos = upper.rfind(opt)
        if pos > p:
            c, p = opt, pos
    return c
