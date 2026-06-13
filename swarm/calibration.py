"""Startup calibration: measure GPU/CPU agent concurrency (not hand-set).

A soft-coded measurement from the actual machine, run before chat starts:
  - GPU agents  = usable VRAM / estimated per-model VRAM (from the model probe)
  - CPU agents  = logical cores * CALIBRATION_CPU_FRACTION
The results override any `MAX_ACTIVE_*=auto` settings in memory. Explicit numbers
in settings are left alone.
"""
from __future__ import annotations

import os


def calibrate(settings, probe, monitor, events=None) -> dict:
    cpu_frac = settings.get_float("CALIBRATION_CPU_FRACTION", 1.0) or 1.0
    vram_frac = settings.get_float("CALIBRATION_VRAM_FRACTION", 0.9) or 0.9

    cores = os.cpu_count() or 4
    cpu_agents = max(1, int(cores * cpu_frac))

    gpu_agents = 1
    total_vram = monitor.vram_total_mb()
    model = settings.get("DEFAULT_MODEL")
    model_vram = None
    if total_vram and model:
        try:
            info = probe.get(settings.require("OLLAMA_GPU_ENDPOINT"), model)
            model_vram = info.est_vram_mb
        except Exception:  # noqa: BLE001
            model_vram = None
        if model_vram:
            gpu_agents = max(1, int((total_vram * vram_frac) // model_vram))

    total_agents = gpu_agents + cpu_agents
    measured = {
        "MAX_ACTIVE_GPU_AGENTS": gpu_agents,
        "MAX_ACTIVE_CPU_AGENTS": cpu_agents,
        "MAX_ACTIVE_AGENTS_TOTAL": total_agents,
        "MAX_ACTIVE_SANDBOXES": total_agents,
        "MAX_ACTIVE_TERMINALS": total_agents,
    }
    for key, val in measured.items():
        if settings.is_auto(key) or settings.get(key) is None:
            settings._v[key] = str(val)

    if events:
        vram_note = (f"{total_vram}MB VRAM / ~{model_vram}MB per model"
                     if total_vram and model_vram else "no GPU detected")
        events.chat(f"Calibration: GPU agents={settings.get('MAX_ACTIVE_GPU_AGENTS')}, "
                    f"CPU agents={settings.get('MAX_ACTIVE_CPU_AGENTS')} "
                    f"({cores} cores, {vram_note}).")
    return {"cores": cores, "total_vram_mb": total_vram, "model_vram_mb": model_vram, **measured}
