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

    # --oneprompt "task": skip the chat/confirm dialogue and spawn immediately.
    # With no task given, fall through to the normal interactive chat.
    oneprompt = bool(argv) and argv[0] == "--oneprompt"
    if oneprompt:
        argv = argv[1:]
        if not " ".join(argv).strip():
            oneprompt = False  # nothing to run; just enter the chat

    rt = build_runtime()
    docker_preflight(rt.settings, rt.logbook)

    # Stream the primary's visible replies to stdout chunk-by-chunk.
    def on_token(delta: str) -> None:
        sys.stdout.write(delta)
        sys.stdout.flush()

    primary = PrimaryAgent(rt, on_token=on_token)

    # Preload the model so the very first message isn't stuck waiting for it.
    model_name = rt.model._model_name("primary")
    rt.logbook.chat(f"loading model {model_name} ... (this can take a moment)")
    try:
        rt.model.warmup("primary")
    except OllamaError as e:
        rt.logbook.chat(f"warning: could not load the model - is Ollama running? ({e})")

    if oneprompt:
        try:
            primary.run_once(" ".join(argv))
            print()
            return 0
        finally:
            rt.executor.shutdown()

    rt.logbook.chat("ready - describe your goal. End a line with \\ to continue it "
                    "on the next line. (Ctrl-C cancels a running swarm, Ctrl-D quits)")

    try:
        if argv:
            primary.send(" ".join(argv))
            print()
            return 0

        while True:
            try:
                line = _read_multiline()
            except (EOFError, KeyboardInterrupt):
                rt.logbook.chat("\nbye.")
                return 0
            if not line.strip():
                continue
            try:
                primary.send(line)   # streams to stdout as it generates
                print()
            except KeyboardInterrupt:
                # Ctrl-C during a swarm: abort it and return to the prompt.
                rt.logbook.chat("\n[cancelled] swarm stopped - back to you.")
    finally:
        rt.executor.shutdown()


def _read_multiline() -> str:
    """Read a user message. A line ending in a backslash continues on the next
    line (terminals can't distinguish Shift+Enter from Enter, so backslash is the
    portable multi-line marker)."""
    prompt, parts = "\nyou> ", []
    while True:
        seg = input(prompt)
        if seg.endswith("\\"):
            parts.append(seg[:-1])
            prompt = "... "
            continue
        parts.append(seg)
        return "\n".join(parts)


if __name__ == "__main__":
    raise SystemExit(main())
