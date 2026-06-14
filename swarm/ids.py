"""Sequential, human-readable IDs (swarm_0001, agent_0014, sandbox_0042...)."""
from __future__ import annotations

import threading

_lock = threading.Lock()
_counters: dict[str, int] = {}


def next_id(prefix: str, width: int = 4) -> str:
    with _lock:
        n = _counters.get(prefix, 0) + 1
        _counters[prefix] = n
    return f"{prefix}_{n:0{width}d}"


def seed(prefix: str, value: int) -> None:
    """Seed a counter (e.g. when resuming from an existing database)."""
    with _lock:
        _counters[prefix] = max(_counters.get(prefix, 0), value)
