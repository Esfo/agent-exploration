"""Entrypoint for recursive_local_swarm (spec section 29).

Usage:
    python -m swarm.main                 # interactive chat REPL
    python -m swarm.main "build me X"    # one-shot goal, then exit
"""
from __future__ import annotations

import sys
from pathlib import Path

from . import ids
from .agent_loop import AgentRunner, RuntimeContext
from .branching import BranchManager
from .calibration import calibrate
from .chat_interface import ChatInterface
from .context_builder import ContextBuilder
from .control import RunControl
from .db import DB
from .memory import MemoryStore
from .model_probe import ProbeCache
from .model_selector import ModelSelector
from .ollama_client import OllamaClient
from .progress import EventBus
from .resources import ResourceMonitor
from .sandbox import docker_preflight, select_executor
from .scheduler import Scheduler
from .settings import Settings
from .web_cache import WebCache

DEFAULT_SETTINGS = "settings/main.settings"


def _seed_ids(db) -> None:
    """Resume ID counters past any rows already in the database."""
    for prefix, table in (("swarm", "swarms"), ("agent", "agents")):
        rows = db.conn.execute(f"SELECT id FROM {table}").fetchall()
        for r in rows:
            try:
                ids.seed(prefix, int(str(r["id"]).rsplit("_", 1)[-1]))
            except (ValueError, IndexError):
                pass


def build_runtime(settings_path: str = DEFAULT_SETTINGS, client=None):
    root = Path(__file__).resolve().parent.parent
    settings = Settings.load(root / settings_path)

    db = DB(settings.path("DATABASE_PATH"), Path(__file__).resolve().parent / "schema.sql")
    _seed_ids(db)

    show_flags = {k: settings.get_bool(k, True) for k in settings.as_dict() if k.startswith("CHAT_SHOW_")}
    events = EventBus(settings.path("LOG_DIR"), db=db, show=show_flags)

    probe = ProbeCache(settings.path("RUNTIME_DIR") / "config_cache.json")
    selector = ModelSelector(settings, probe)
    client = client or OllamaClient()
    builder = ContextBuilder(settings)
    executor = select_executor(settings)
    web_cache = WebCache(settings, db)
    monitor = ResourceMonitor(str(settings.root))
    # Measure GPU/CPU agent concurrency from the machine before building the
    # scheduler (overrides any MAX_ACTIVE_*=auto in memory).
    calibrate(settings, probe, monitor, events)
    scheduler = Scheduler(settings, monitor, events)

    ctx = RuntimeContext(settings, db, events, selector, client, builder, executor, web_cache)
    ctx.scheduler = scheduler
    ctx.memory = MemoryStore(db)
    ctx.branch = BranchManager(db)
    ctx.control = RunControl()
    docker_preflight(settings, events)
    runner = AgentRunner(ctx)
    return ctx, runner


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    ctx, runner = build_runtime()
    chat = ChatInterface(ctx, runner)

    ctx.events.chat(
        f"recursive_local_swarm {ctx.settings.get('RUNTIME_VERSION')} ready.\n"
        "Type to talk to the progenitor — it decides (per its instructions) whether "
        "to just answer or spawn a swarm. /ask <msg> for a raw model line. /help for more."
    )

    if argv:
        chat.handle(" ".join(argv))
        return 0

    while True:
        try:
            line = input("\nyou> ")
        except (EOFError, KeyboardInterrupt):
            ctx.events.chat("\nbye.")
            return 0
        if not chat.handle(line):
            ctx.events.chat("bye.")
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
