"""Entry point.

    python -m swarm.main                 interactive chat with the primary agent
    python -m swarm.main "build me X"     one-shot goal, then exit
    python -m swarm.main --initiate       build the hardened sandbox image
"""
from __future__ import annotations

import sys
from pathlib import Path

try:                        # gives input() arrow-key / delete / history editing
    import readline  # noqa: F401
except ImportError:         # not available on some platforms; input() still works
    pass

from .instructions import Instructions
from .logbook import Logbook
from .model import Model
from .ollama_client import OllamaClient, OllamaError
from .primary import PrimaryAgent
from .runtime import Runtime
from .sandbox import build_image, docker_preflight, select_executor
from .settings import Settings

DEFAULT_SETTINGS = "settings/main.settings"


def build_runtime(settings_path: str = DEFAULT_SETTINGS, client=None) -> Runtime:
    root = Path(__file__).resolve().parent.parent
    settings = Settings.load(root / settings_path)
    instr = Instructions(settings.path("INSTRUCTIONS_DIR"))
    logbook = Logbook(settings.path("LOG_DIR"))
    model = Model(settings, client or OllamaClient())
    executor = select_executor(settings)
    return Runtime(settings=settings, model=model, instr=instr, logbook=logbook,
                   executor=executor, work_root=settings.path("SANDBOX_WORKDIR"),
                   primary_dir=settings.path("PRIMARY_DIR"))


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    if argv and argv[0] == "--initiate":
        ok = build_image()
        return 0 if ok else 1

    rt = build_runtime()
    docker_preflight(rt.settings, rt.logbook)
    primary = PrimaryAgent(rt)

    # Preload the model so the very first message isn't stuck waiting for it.
    model_name = rt.model._model_name("primary")
    rt.logbook.chat(f"loading model {model_name} … (this can take a moment)")
    try:
        rt.model.warmup("primary")
    except OllamaError as e:
        rt.logbook.chat(f"warning: could not load the model — is Ollama running? ({e})")
    rt.logbook.chat("ready — describe your goal. "
                    "(Ctrl-C cancels a running swarm, Ctrl-D quits)")

    try:
        if argv:
            print(primary.send(" ".join(argv)))
            return 0

        while True:
            try:
                line = input("\nyou> ")
            except (EOFError, KeyboardInterrupt):
                rt.logbook.chat("\nbye.")
                return 0
            if not line.strip():
                continue
            try:
                print(primary.send(line))
            except KeyboardInterrupt:
                # Ctrl-C during a swarm: abort it and return to the prompt.
                rt.logbook.chat("\n[cancelled] swarm stopped — back to you.")
    finally:
        rt.executor.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
