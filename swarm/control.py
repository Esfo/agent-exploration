"""Cooperative run control for live commands (spec section 4).

Lets the REPL pause/resume/cancel a running swarm and stop after the current
wave, while the swarm runs in a background thread. The agent loop checks this
object at safe points (the top of each iteration and before starting a new wave
of children), so control is cooperative — no thread is killed mid-write.
"""
from __future__ import annotations

import threading


class RunControl:
    def __init__(self):
        self._cond = threading.Condition()
        self._paused = False
        self._cancel_all = False
        self._cancelled: set[str] = set()
        self._stop_after_wave = False

    def pause(self) -> None:
        with self._cond:
            self._paused = True

    def resume(self) -> None:
        with self._cond:
            self._paused = False
            self._cond.notify_all()

    def cancel(self, agent_id: str | None = None) -> None:
        with self._cond:
            if agent_id:
                self._cancelled.add(agent_id)
            else:
                self._cancel_all = True
            self._cond.notify_all()

    def stop_after_wave(self) -> None:
        with self._cond:
            self._stop_after_wave = True

    def reset(self) -> None:
        with self._cond:
            self._paused = False
            self._cancel_all = False
            self._cancelled.clear()
            self._stop_after_wave = False
            self._cond.notify_all()

    @property
    def paused(self) -> bool:
        with self._cond:
            return self._paused

    def is_cancelled(self, agent_id: str) -> bool:
        with self._cond:
            return self._cancel_all or agent_id in self._cancelled

    def should_stop_waves(self) -> bool:
        with self._cond:
            return self._stop_after_wave

    def wait_if_paused(self, agent_id: str) -> None:
        """Block while paused, returning early if this agent gets cancelled."""
        with self._cond:
            while self._paused and not self._cancel_all and agent_id not in self._cancelled:
                self._cond.wait(timeout=0.5)
