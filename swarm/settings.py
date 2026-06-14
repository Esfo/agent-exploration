"""Settings loader for settings/main.settings (spec section 6).

Parses plaintext KEY=VALUE lines. Blank lines and lines starting with '#'
are ignored. Invalid active lines fail loudly with their line number.
"""
from __future__ import annotations

from pathlib import Path

PLACEHOLDER_MODEL = "<PLACEHOLDER_OLLAMA_MODEL>"

# Keys that must be present for the runtime to start.
REQUIRED_KEYS = (
    "RUNTIME_NAME",
    "OLLAMA_GPU_ENDPOINT",
    "OLLAMA_CPU_ENDPOINT",
    "DEFAULT_MODEL",
    "DATABASE_PATH",
)

_TRUE = {"true", "1", "yes", "on"}
_FALSE = {"false", "0", "no", "off"}


class SettingsError(Exception):
    """Raised when settings fail to load or validate."""


class Settings:
    def __init__(self, values: dict[str, str], root: Path):
        self._v = values
        self.root = root

    # ----- construction -----
    @classmethod
    def load(cls, path: str | Path) -> "Settings":
        path = Path(path)
        if not path.exists():
            raise SettingsError(f"settings file not found: {path}")
        values: dict[str, str] = {}
        for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                raise SettingsError(f"{path}:{lineno}: expected KEY=VALUE, got: {raw!r}")
            key, _, val = line.partition("=")
            key = key.strip()
            if not key:
                raise SettingsError(f"{path}:{lineno}: empty key")
            values[key] = val.strip()
        missing = [k for k in REQUIRED_KEYS if k not in values]
        if missing:
            raise SettingsError(f"{path}: missing required keys: {', '.join(missing)}")
        root = path.parent.parent  # settings/main.settings -> project root
        return cls(values, root)

    # ----- typed accessors -----
    def get(self, key: str, default: str | None = None) -> str | None:
        return self._v.get(key, default)

    def require(self, key: str) -> str:
        if key not in self._v:
            raise SettingsError(f"missing required key: {key}")
        return self._v[key]

    def get_int(self, key: str, default: int | None = None) -> int | None:
        v = self._v.get(key)
        if v is None:
            return default
        if v.lower() in ("auto", "unlimited"):
            return None
        try:
            return int(v)
        except ValueError as e:
            raise SettingsError(f"{key}: expected int, got {v!r}") from e

    def get_float(self, key: str, default: float | None = None) -> float | None:
        v = self._v.get(key)
        if v is None:
            return default
        try:
            return float(v)
        except ValueError as e:
            raise SettingsError(f"{key}: expected float, got {v!r}") from e

    def get_bool(self, key: str, default: bool = False) -> bool:
        v = self._v.get(key)
        if v is None:
            return default
        lv = v.lower()
        if lv in _TRUE:
            return True
        if lv in _FALSE:
            return False
        raise SettingsError(f"{key}: expected bool, got {v!r}")

    def is_auto(self, key: str) -> bool:
        return (self._v.get(key, "").lower() == "auto")

    def is_unlimited(self, key: str) -> bool:
        return (self._v.get(key, "").lower() == "unlimited")

    def path(self, key: str) -> Path:
        """Resolve a directory/file setting relative to the project root."""
        return (self.root / self.require(key)).resolve()

    def as_dict(self) -> dict[str, str]:
        return dict(self._v)
