"""Parser for <<tool:name>> ... <</tool>> blocks (spec sections 5, 10, 20).

Small local models are unreliable JSON emitters, so this parser is deliberately
tolerant:
    - tolerates markdown code fences inside/around the block
    - tolerates a trailing comma before } or ]
    - tolerates single quotes if double-quote parse fails
    - tolerates missing closing <</tool>> at end of message
Each parsed block returns a ToolCall; malformed JSON is reported via .error so
the agent loop can feed a correction back instead of crashing.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

# Opening tag; closing tag optional so we can recover a trailing block.
_OPEN = re.compile(r"<<\s*tool\s*:\s*([a-zA-Z0-9_]+)\s*>>", re.IGNORECASE)
_CLOSE = re.compile(r"<<\s*/\s*tool\s*>>", re.IGNORECASE)
_FENCE = re.compile(r"^\s*```[a-zA-Z0-9]*\s*$", re.MULTILINE)


@dataclass
class ToolCall:
    name: str
    args: dict = field(default_factory=dict)
    raw: str = ""
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def _strip_fences(s: str) -> str:
    return _FENCE.sub("", s).strip()


def _loose_json(s: str) -> tuple[dict | None, str | None]:
    s = _strip_fences(s).strip()
    if not s:
        return {}, None
    # Pull out the outermost {...} if there is leading/trailing prose.
    first, last = s.find("{"), s.rfind("}")
    if first != -1 and last != -1 and last > first:
        s = s[first:last + 1]
    try:
        return json.loads(s), None
    except json.JSONDecodeError:
        pass
    # Remove trailing commas: ",]" / ",}".
    repaired = re.sub(r",(\s*[}\]])", r"\1", s)
    try:
        return json.loads(repaired), None
    except json.JSONDecodeError:
        pass
    # Last resort: single -> double quotes.
    try:
        return json.loads(repaired.replace("'", '"')), None
    except json.JSONDecodeError as e:
        return None, f"invalid JSON: {e}"


def parse(text: str) -> list[ToolCall]:
    calls: list[ToolCall] = []
    for m in _OPEN.finditer(text):
        name = m.group(1).strip()
        body_start = m.end()
        close = _CLOSE.search(text, body_start)
        # Stop body at the next opening tag if there is no close before it.
        next_open = _OPEN.search(text, body_start)
        if close and (not next_open or close.start() < next_open.start()):
            body = text[body_start:close.start()]
        elif next_open:
            body = text[body_start:next_open.start()]
        else:
            body = text[body_start:]
        args, err = _loose_json(body)
        calls.append(ToolCall(name=name, args=args or {}, raw=body.strip(), error=err))
    return calls


def has_tool_block(text: str) -> bool:
    return _OPEN.search(text) is not None
