"""Shared fixtures: a tmp project copy + a scripted mock Ollama client."""
import shutil
from pathlib import Path

import pytest

from swarm.instructions import Instructions
from swarm.logbook import Logbook
from swarm.model import Model
from swarm.ollama_client import ChatResponse
from swarm.runtime import Runtime
from swarm.sandbox import SubprocessExecutor
from swarm.settings import Settings

REPO = Path(__file__).resolve().parent.parent


class MockClient:
    """Maps the last user message to a canned assistant response so the
    orchestration can be exercised offline.

    ``script`` is called as ``script(last_user, system, call_index) -> str``.
    """

    def __init__(self, script):
        self.script = script
        self.calls = []

    def chat(self, endpoint, model, messages, options=None, timeout=None):
        self.calls.append({"model": model, "messages": list(messages)})
        last_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        content = self.script(last_user, system, len(self.calls))
        return ChatResponse(content=content, telemetry={"selected_model": model})


@pytest.fixture
def project(tmp_path):
    for d in ("settings", "instructions"):
        shutil.copytree(REPO / d, tmp_path / d)
    sp = tmp_path / "settings" / "main.settings"
    text = sp.read_text(encoding="utf-8").replace(
        "DEFAULT_MODEL=qwen2.5-coder:7b", "DEFAULT_MODEL=mock-model:latest")
    sp.write_text(text, encoding="utf-8")
    return tmp_path


def make_runtime(project_dir, client, *, sink=None) -> Runtime:
    settings = Settings.load(project_dir / "settings" / "main.settings")
    instr = Instructions(settings.path("INSTRUCTIONS_DIR"))
    logbook = Logbook(settings.path("LOG_DIR"), sink=sink or (lambda *_: None))
    model = Model(settings, client)
    executor = SubprocessExecutor(settings)
    return Runtime(settings=settings, model=model, instr=instr, logbook=logbook,
                   executor=executor, work_root=settings.path("SANDBOX_WORKDIR"),
                   primary_dir=settings.path("PRIMARY_DIR"))
