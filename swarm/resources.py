"""Resource monitor (spec section 6 resource behavior, section 29 scheduler).

Zero-dependency system metrics: RAM from /proc/meminfo, CPU from /proc/stat,
VRAM from nvidia-smi (optional), disk from os.statvfs. Used by the scheduler to
apply backpressure (queue new inference) when the machine is under pressure.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass


@dataclass
class Snapshot:
    ram_percent: float
    cpu_percent: float
    vram_percent: float | None
    disk_percent: float


class ResourceMonitor:
    def __init__(self, disk_path: str = "."):
        self.disk_path = disk_path
        self._have_nvidia = shutil.which("nvidia-smi") is not None
        self._last_cpu: tuple[int, int] | None = None  # (idle, total)

    # ----- RAM -----
    def ram_percent(self) -> float:
        try:
            with open("/proc/meminfo", encoding="utf-8") as f:
                info = {}
                for line in f:
                    k, _, v = line.partition(":")
                    info[k.strip()] = int(v.strip().split()[0])  # kB
            total = info.get("MemTotal", 0)
            avail = info.get("MemAvailable", info.get("MemFree", 0))
            if total <= 0:
                return 0.0
            return round((total - avail) / total * 100, 1)
        except (OSError, ValueError, KeyError):
            return 0.0

    # ----- CPU (delta between calls) -----
    def cpu_percent(self) -> float:
        try:
            with open("/proc/stat", encoding="utf-8") as f:
                parts = f.readline().split()
            vals = [int(x) for x in parts[1:]]
            idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
            total = sum(vals)
        except (OSError, ValueError, IndexError):
            return 0.0
        if self._last_cpu is None:
            self._last_cpu = (idle, total)
            return 0.0
        prev_idle, prev_total = self._last_cpu
        self._last_cpu = (idle, total)
        dt = total - prev_total
        di = idle - prev_idle
        if dt <= 0:
            return 0.0
        return round((1 - di / dt) * 100, 1)

    # ----- VRAM -----
    def vram_percent(self) -> float | None:
        if not self._have_nvidia:
            return None
        try:
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.used,memory.total",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5, check=True,
            ).stdout.strip()
            used_t = total_t = 0
            for line in out.splitlines():
                u, t = (int(x.strip()) for x in line.split(","))
                used_t += u
                total_t += t
            if total_t <= 0:
                return None
            return round(used_t / total_t * 100, 1)
        except (subprocess.SubprocessError, ValueError, OSError):
            return None

    # ----- disk -----
    def vram_total_mb(self) -> int | None:
        if not self._have_nvidia:
            return None
        try:
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5, check=True,
            ).stdout.strip()
            return sum(int(x.strip()) for x in out.splitlines() if x.strip())
        except (subprocess.SubprocessError, ValueError, OSError):
            return None

    def disk_percent(self) -> float:
        try:
            st = os.statvfs(self.disk_path)
            total = st.f_blocks * st.f_frsize
            free = st.f_bavail * st.f_frsize
            if total <= 0:
                return 0.0
            return round((total - free) / total * 100, 1)
        except OSError:
            return 0.0

    def snapshot(self) -> Snapshot:
        return Snapshot(self.ram_percent(), self.cpu_percent(),
                        self.vram_percent(), self.disk_percent())

    def under_pressure(self, settings, snap: Snapshot | None = None) -> tuple[bool, str]:
        snap = snap or self.snapshot()
        checks = [
            ("RAM", snap.ram_percent, settings.get_int("MAX_RAM_PERCENT", 80)),
            ("CPU", snap.cpu_percent, settings.get_int("MAX_CPU_PERCENT", 85)),
            ("disk", snap.disk_percent, settings.get_int("MAX_DISK_USAGE_PERCENT", 90)),
        ]
        if snap.vram_percent is not None:
            checks.append(("VRAM", snap.vram_percent, settings.get_int("MAX_VRAM_PERCENT", 85)))
        for name, value, limit in checks:
            if limit and value >= limit:
                return True, f"{name} at {value}% (limit {limit}%)"
        return False, ""
