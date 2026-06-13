"""Scheduler: concurrency slots + resource backpressure (spec sections 6, 29).

The expensive shared resources are the model endpoints. Inference is gated by
two bounded semaphores — GPU and CPU — sized from MAX_ACTIVE_GPU_AGENTS /
MAX_ACTIVE_CPU_AGENTS. Agent threads are cheap and may block waiting on their
children, but they only hold an inference slot for the duration of a single
model call, so parents waiting on children never starve the pool (no deadlock).

Before taking a slot, the scheduler checks the resource monitor and queues
(waits) while the machine is under RAM/CPU/VRAM/disk pressure, per
RESOURCE_PRESSURE_ACTION=queue_new_agents. Waiting is capped so it degrades to
best-effort rather than hanging forever.
"""
from __future__ import annotations

import threading
import time
from contextlib import contextmanager

_BIG = 1024  # stands in for "unlimited"


class Scheduler:
    def __init__(self, settings, monitor, events=None):
        self.s = settings
        self.monitor = monitor
        self.events = events
        gpu = settings.get_int("MAX_ACTIVE_GPU_AGENTS")  # None => unlimited
        cpu = settings.get_int("MAX_ACTIVE_CPU_AGENTS")
        self._gpu = threading.BoundedSemaphore(gpu if gpu else _BIG)
        self._cpu = threading.BoundedSemaphore(cpu if cpu else _BIG)
        self._sample_interval = settings.get_float("RESOURCE_SAMPLE_INTERVAL_SECONDS", 2.0) or 2.0
        self._max_pressure_waits = 30  # cap so we never hang forever

    def _wait_for_pressure(self, agent_id: str | None) -> None:
        action = (self.s.get("RESOURCE_PRESSURE_ACTION", "queue_new_agents") or "")
        if action != "queue_new_agents":
            return
        for _ in range(self._max_pressure_waits):
            pressured, reason = self.monitor.under_pressure(self.s)
            if not pressured:
                return
            if self.events:
                self.events.agent_progress(None, agent_id,
                                           f"Queued: resource pressure ({reason})", None,
                                           current_step="waiting_on_resources")
            time.sleep(self._sample_interval)
        # Best-effort: proceed after the cap rather than deadlocking the swarm.

    @contextmanager
    def inference_slot(self, execution_class: str, agent_id: str | None = None):
        self._wait_for_pressure(agent_id)
        sem = self._gpu if execution_class == "gpu" else self._cpu
        sem.acquire()
        try:
            yield
        finally:
            sem.release()
