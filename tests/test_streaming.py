"""Streaming chat: tokens arrive incrementally and accumulate to the full text."""
from conftest import make_runtime

from swarm.ollama_client import ChatResponse


class StreamClient:
    def chat_stream(self, endpoint, model, messages, options=None, on_token=None):
        for chunk in ("Here ", "is ", "the ", "plan."):
            if on_token:
                on_token(chunk)
        return ChatResponse(content="Here is the plan.", telemetry={})

    def chat(self, *a, **k):
        return ChatResponse(content="(non-stream)", telemetry={})


def test_chat_stream_emits_tokens_and_returns_full_text(project):
    rt = make_runtime(project, StreamClient())
    got = []
    out = rt.model.chat_stream("primary", [{"role": "user", "content": "hi"}], got.append)
    assert got == ["Here ", "is ", "the ", "plan."]
    assert out == "Here is the plan."
