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
from .live import Live
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


def _reset_workspace(settings) -> None:
    """Clear the runtime workspace folders so each launch starts fresh."""
    import shutil
    for key in ("PRIMARY_DIR", "SANDBOX_WORKDIR", "RESULTS_DIR"):
        try:
            path = Path(settings.path(key))
        except Exception:  # noqa: BLE001 - key not set
            continue
        shutil.rmtree(path, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    if argv and argv[0] == "--initiate":
        ok = build_image()
        return 0 if ok else 1

    # --oneprompt: skip the chat/confirm dialogue and spawn a swarm immediately.
    # The task can be given on the command line, or typed once at the prompt.
    # (To use the conversational chat instead, just run without --oneprompt.)
    oneprompt = bool(argv) and argv[0] == "--oneprompt"
    if oneprompt:
        argv = argv[1:]

    rt = build_runtime()
    _reset_workspace(rt.settings)        # fresh workspace on every launch

    # Live display: model generation streams into a pinned bottom buffer; the
    # one-line notices scroll above it. Falls back to plain output off-TTY.
    live = Live(height=rt.settings.get_int("LIVE_BUFFER_LINES", 3) or 3,
                enabled=rt.settings.get_bool("LIVE_DISPLAY", True))
    if live.enabled:
        rt.logbook.sink = live.log
        rt.model.live = live
        primary = PrimaryAgent(rt, on_token=None)
    else:
        def on_token(delta: str) -> None:
            sys.stdout.write(delta)
            sys.stdout.flush()
        primary = PrimaryAgent(rt, on_token=on_token)

    docker_preflight(rt.settings, rt.logbook)

    # Preload the model silently so the first message isn't stuck waiting for it.
    try:
        rt.model.warmup("primary")
    except OllamaError as e:
        rt.logbook.chat(f"could not load the model - is Ollama running? ({e})")

    def deliver(text: str) -> None:
        """Show a turn's durable output (committed above the live buffer)."""
        if live.enabled:
            live.finish()
            live.log(text)
        else:
            print()

    if oneprompt:
        try:
            task = " ".join(argv).strip()
            if not task:
                try:
                    task = _read_multiline().strip()
                except (EOFError, KeyboardInterrupt):
                    return 0
            if not task:
                return 0
            try:
                deliver(primary.run_once(task))
            except KeyboardInterrupt:
                live.finish()
                rt.logbook.chat("[cancelled] swarm stopped - back to you.")
            return 0
        finally:
            rt.executor.shutdown()

    try:
        if argv:
            deliver(primary.send(" ".join(argv)))
            return 0

        while True:
            try:
                line = _read_multiline()
            except EOFError:           # Ctrl-D: quit
                rt.logbook.chat("bye.")
                return 0
            except KeyboardInterrupt:  # Ctrl-C at the prompt: ignore, new prompt
                print()
                continue
            if not line.strip():
                continue
            try:
                deliver(primary.send(line))
            except KeyboardInterrupt:
                # Ctrl-C during a swarm: abort it and return to the prompt.
                live.finish()
                rt.logbook.chat("[cancelled] swarm stopped - back to you.")
    finally:
        live.finish()
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
