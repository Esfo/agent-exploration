"""Model probe: pre-run detection of a model's native capabilities.

The user wants context size / memory footprint to come from the model itself
rather than hard-coded numbers. Ollama exposes this via POST /api/show, which
returns:
    - model_info: includes "<arch>.context_length", "<arch>.embedding_length", ...
    - details: parameter_size (e.g. "7.6B"), quantization_level (e.g. "Q4_K_M")
    - capabilities: e.g. ["completion", "tools", "insert", "vision"]

We read the native context_length and parameter size, estimate a memory
footprint, and cache the result in runtime/config_cache.json so we only probe
each model once per session. If Ollama is unreachable, callers fall back to
settings values.
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass
class ModelInfo:
    name: str
    native_num_ctx: int | None        # model's trained context length
    parameter_size: str | None        # e.g. "7.6B"
    parameter_count: int | None       # raw param count if available
    quantization: str | None          # e.g. "Q4_K_M"
    capabilities: list[str]           # e.g. ["completion", "tools"]
    est_vram_mb: int | None           # rough weights-only footprint estimate
    probed_at: float
    source: str                       # "ollama" | "cache" | "unavailable"

    def supports_tools(self) -> bool:
        return "tools" in (self.capabilities or [])


def _parse_param_count(parameter_size: str | None, model_info: dict) -> int | None:
    # Prefer an exact count from model_info if present.
    for k, v in (model_info or {}).items():
        if k.endswith("parameter_count") and isinstance(v, (int, float)):
            return int(v)
    if not parameter_size:
        return None
    m = re.match(r"([\d.]+)\s*([BMK])?", parameter_size.strip(), re.IGNORECASE)
    if not m:
        return None
    num = float(m.group(1))
    mult = {"K": 1e3, "M": 1e6, "B": 1e9, None: 1.0}[
        (m.group(2) or "").upper() or None
    ]
    return int(num * mult)


def _bytes_per_weight(quant: str | None) -> float:
    """Approximate bytes-per-weight for common quantizations (weights only)."""
    if not quant:
        return 2.0  # assume fp16-ish
    q = quant.upper()
    table = {
        "Q2": 0.33, "Q3": 0.43, "Q4": 0.55, "Q5": 0.68,
        "Q6": 0.82, "Q8": 1.06, "F16": 2.0, "FP16": 2.0, "F32": 4.0,
    }
    for prefix, bpw in table.items():
        if q.startswith(prefix):
            return bpw
    return 1.0


def _find_context_length(model_info: dict) -> int | None:
    if not model_info:
        return None
    for k, v in model_info.items():
        if k.endswith(".context_length") and isinstance(v, (int, float)):
            return int(v)
    # Some payloads use a flat "context_length".
    v = model_info.get("context_length")
    return int(v) if isinstance(v, (int, float)) else None


def probe_ollama(endpoint: str, model: str, timeout: float = 10.0) -> ModelInfo | None:
    """Hit /api/show for one model. Returns None if unreachable."""
    url = endpoint.rstrip("/") + "/api/show"
    data = json.dumps({"model": model}).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return None

    model_info = payload.get("model_info") or {}
    details = payload.get("details") or {}
    caps = payload.get("capabilities") or []
    param_size = details.get("parameter_size")
    quant = details.get("quantization_level")
    param_count = _parse_param_count(param_size, model_info)
    est_vram = None
    if param_count:
        est_vram = int(param_count * _bytes_per_weight(quant) / (1024 * 1024))

    return ModelInfo(
        name=model,
        native_num_ctx=_find_context_length(model_info),
        parameter_size=param_size,
        parameter_count=param_count,
        quantization=quant,
        capabilities=list(caps),
        est_vram_mb=est_vram,
        probed_at=time.time(),
        source="ollama",
    )


class ProbeCache:
    """Caches ModelInfo to runtime/config_cache.json across the session."""

    def __init__(self, cache_path: str | Path):
        self.cache_path = Path(cache_path)
        self._cache: dict[str, dict] = {}
        if self.cache_path.exists():
            try:
                self._cache = json.loads(self.cache_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._cache = {}

    def get(self, endpoint: str, model: str, *, max_age_s: float = 86400) -> ModelInfo:
        key = f"{endpoint}::{model}"
        cached = self._cache.get(key)
        if cached and (time.time() - cached.get("probed_at", 0)) < max_age_s:
            info = ModelInfo(**cached)
            info.source = "cache"
            return info

        info = probe_ollama(endpoint, model)
        if info is None:
            # Unavailable: return a stub so callers can fall back to settings.
            return ModelInfo(
                name=model, native_num_ctx=None, parameter_size=None,
                parameter_count=None, quantization=None, capabilities=[],
                est_vram_mb=None, probed_at=time.time(), source="unavailable",
            )
        self._cache[key] = asdict(info)
        self._flush()
        return info

    def _flush(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(self._cache, indent=2), encoding="utf-8")
