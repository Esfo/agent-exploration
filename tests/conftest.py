"""Shared fixtures: a tmp project copy + a mock Ollama client."""
import shutil
from pathlib import Path

import pytest

from swarm.agent_loop import AgentRunner, RuntimeContext
from swarm.context_builder import ContextBuilder
from swarm.db import DB
from swarm.model_probe import ProbeCache
from swarm.model_selector import ModelSelector
from swarm.progress import EventBus
from swarm.settings import Settings

REPO = Path(__file__).resolve().parent.parent


class MockClient:
    """Scripted Ollama replacement. Maps a predicate over the last user message
    to a canned assistant response so the agent loop can be exercised offline."""

    def __init__(self, script):
        self.script = script
        self.calls = []

    def chat(self, endpoint, model, messages, options=None, timeout=None):
        from swarm.ollama_client import ChatResponse
        self.calls.append({"model": model, "messages": messages})
        last_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        content = self.script(last_user, model, len(self.calls))
        return ChatResponse(content=content, telemetry={
            "selected_model": model, "endpoint": endpoint,
            "prompt_eval_count": 10, "eval_count": 20, "duration_ms": 5,
            "done_reason": "stop",
        })


@pytest.fixture
def project(tmp_path):
    """Copy the static scaffold into a tmp dir with a concrete DEFAULT_MODEL."""
    for d in ("settings", "instructions", "prompts"):
        shutil.copytree(REPO / d, tmp_path / d)
    (tmp_path / "swarm").mkdir()
    shutil.copy(REPO / "swarm" / "schema.sql", tmp_path / "swarm" / "schema.sql")

    sp = tmp_path / "settings" / "main.settings"
    text = sp.read_text(encoding="utf-8").replace(
        "DEFAULT_MODEL=qwen2.5-coder:7b", "DEFAULT_MODEL=mock-model:latest"
    ).replace("CHECK_GATE_ENABLED=true", "CHECK_GATE_ENABLED=false"
    ).replace("RESOURCE_PRESSURE_ACTION=queue_new_agents", "RESOURCE_PRESSURE_ACTION=off"
    ).replace("CODE_PIPELINE_ENABLED=true", "CODE_PIPELINE_ENABLED=false")
    sp.write_text(text, encoding="utf-8")
    return tmp_path


def make_runtime(project_dir, client):
    settings = Settings.load(project_dir / "settings" / "main.settings")
    db = DB(project_dir / "runtime" / "state.sqlite", project_dir / "swarm" / "schema.sql")
    events = EventBus(project_dir / "logs", db=db, sink=lambda *_: None,
                      show={k: False for k in ("CHAT_SHOW_AGENT_START", "CHAT_SHOW_AGENT_PROGRESS",
                                               "CHAT_SHOW_AGENT_FINISH", "CHAT_SHOW_SPAWN_EVENTS")})
    probe = ProbeCache(project_dir / "runtime" / "config_cache.json")
    selector = ModelSelector(settings, probe)
    builder = ContextBuilder(settings)
    from swarm.sandbox import SubprocessExecutor
    from swarm.web_cache import WebCache
    executor = SubprocessExecutor(settings)
    web_cache = WebCache(settings, db)
    ctx = RuntimeContext(settings, db, events, selector, client, builder, executor, web_cache)
    runner = AgentRunner(ctx)
    return ctx, runner
