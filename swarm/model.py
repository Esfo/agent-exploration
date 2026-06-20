"""Per-role model resolution and a single chat entry point.

Resolution order for the model name: ``DEFAULT_<PREFIX>_MODEL`` (when set and
not a placeholder) then ``DEFAULT_MODEL``. Context/output/temperature come from
``<PREFIX>_NUM_CTX`` / ``<PREFIX>_NUM_PREDICT`` / ``<PREFIX>_TEMPERATURE`` with
sensible fallbacks. GPU vs CPU endpoint is chosen by ``ROUTE_<PREFIX>_TO_GPU``.
"""
from __future__ import annotations

from .summarizer import Summarizer

# role -> settings prefix
ROLE_PREFIX = {
    "primary": "PRIMARY",
    "coding": "CODE",
    "math": "MATH",
    "optimization": "OPTIMIZATION",
    "philosophizing": "PHILOSOPHER",
    "testing": "TESTER",
    "zipper": "ZIPPER",
    "summarizer": "SUMMARIZER",
}

_PLACEHOLDER = "<PLACEHOLDER_OLLAMA_MODEL>"


class Model:
    def __init__(self, settings, client):
        self.s = settings
        self.client = client
        self.summarizer = Summarizer(self)

    def _prefix(self, role: str) -> str:
        return ROLE_PREFIX.get(role, "DEFAULT")

    def _model_name(self, role: str) -> str:
        prefix = self._prefix(role)
        name = self.s.get(f"DEFAULT_{prefix}_MODEL")
        if not name or name == _PLACEHOLDER:
            name = self.s.get("DEFAULT_MODEL")
        return name

    def _endpoint(self, role: str) -> str:
        prefix = self._prefix(role)
        to_gpu = self.s.get_bool(f"ROUTE_{prefix}_TO_GPU", True)
        key = "OLLAMA_GPU_ENDPOINT" if to_gpu else "OLLAMA_CPU_ENDPOINT"
        return self.s.get(key) or self.s.get("OLLAMA_GPU_ENDPOINT")

    def _options(self, role: str) -> dict:
        prefix = self._prefix(role)
        num_ctx = self.s.get_int(f"{prefix}_NUM_CTX", None) or self.s.get_int("DEFAULT_NUM_CTX", 8192) or 8192
        num_predict = (self.s.get_int(f"{prefix}_NUM_PREDICT", None)
                       or self.s.get_int("DEFAULT_NUM_PREDICT", 2048) or 2048)
        temperature = self.s.get_float(f"{prefix}_TEMPERATURE", None)
        if temperature is None:
            temperature = self.s.get_float("DEFAULT_TEMPERATURE", 0.3) or 0.3
        return {"num_ctx": num_ctx, "num_predict": num_predict, "temperature": temperature}

    def chat(self, role: str, messages: list[dict]) -> str:
        """One chat turn for ``role``. Returns the assistant's text.

        The history is first compressed in place if it exceeds the role's
        context budget (top-down summarize-on-overflow)."""
        self.summarizer.fit(role, messages)
        resp = self.client.chat(
            endpoint=self._endpoint(role),
            model=self._model_name(role),
            messages=messages,
            options=self._options(role),
        )
        return (resp.content or "").strip()
