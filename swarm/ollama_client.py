"""Minimal Ollama client (spec section 11/12/29).

Uses only the standard library so the runtime has no install-time deps.
Calls POST /api/chat with stream=false and returns content + telemetry.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field


class OllamaError(Exception):
    pass


@dataclass
class ChatResponse:
    content: str
    telemetry: dict = field(default_factory=dict)


class OllamaClient:
    def __init__(self, default_timeout: float = 600.0):
        self.default_timeout = default_timeout

    def chat(self, endpoint: str, model: str, messages: list[dict],
             options: dict | None = None, timeout: float | None = None) -> ChatResponse:
        url = endpoint.rstrip("/") + "/api/chat"
        body = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": options or {},
        }
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.default_timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            raise OllamaError(f"ollama HTTP {e.code} at {url}: {detail}") from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise OllamaError(f"ollama unreachable at {url}: {e}") from e

        message = payload.get("message") or {}
        content = message.get("content", "")
        telemetry = {
            "selected_model": model,
            "endpoint": endpoint,
            "num_ctx": (options or {}).get("num_ctx"),
            "num_predict": (options or {}).get("num_predict"),
            "temperature": (options or {}).get("temperature"),
            "prompt_eval_count": payload.get("prompt_eval_count"),
            "eval_count": payload.get("eval_count"),
            "total_duration": payload.get("total_duration"),
            "duration_ms": (payload.get("total_duration") or 0) // 1_000_000,
            "done_reason": payload.get("done_reason"),
        }
        return ChatResponse(content=content, telemetry=telemetry)
