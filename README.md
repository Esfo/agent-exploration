# recursive_local_swarm

A local, chat-driven, recursively-agentic LLM swarm that runs on Ollama. You talk
to a **progenitor** agent; it decides (per editable instruction files) whether to
answer directly or spawn a recursive swarm of agents that write code, run it in a
sandbox, reconcile each other's work, and report back. Runtime is **pure stdlib**
(no third-party deps); `pytest` is dev-only.

## Docs

- [`docs/PLAN.md`](docs/PLAN.md) — build status + design decisions
- [`docs/CHECKS.md`](docs/CHECKS.md) — **user-list checks** (the finish-gate)
- [`docs/CONTEXT.md`](docs/CONTEXT.md) — conversation inheritance, purpose, summarizer
- [`docs/COMMANDS.md`](docs/COMMANDS.md) — chat & slash command reference

## What's implemented

All six prototypes plus the owner's design corrections. Tested offline with a
mock model (`python -m pytest -q`, 92 tests):

- **Core loop** — settings/instruction/prompt loaders; model probe (auto context
  size via `/api/show`); per-role model selection; stdlib Ollama client; SQLite
  state; tolerant `<<tool:...>>` parser; recursive spawning with ceilings.
- **Execution** — path/command/cwd guards (Python force-jails every file write
  into the agent's dir; the agent never picks the location); sandboxed
  `python`/`shell` and persistent terminals behind one `Executor` interface with
  **subprocess and Docker** backends (Docker auto-selected when the daemon is up).
- **Web** — `curl`/`search_web_cache`/`read_cached_page` with an SSRF guard and a
  freshness-based on-disk cache.
- **Reconciliation** — `request_review`/`request_integration`/`request_testing`/
  `request_fix` spawn the matching agent role.
- **Profiling/optimization** — `profile` (cProfile + baseline) and `optimize`
  (sandboxed before/after validation).
- **Scheduler** — stdlib resource monitor (RAM/CPU/VRAM/disk) + GPU/CPU inference
  slots with backpressure; **parallel** agents over a thread-safe shared DB.
- **Memory & branching** — `/remember`/`/forget`/`/memories`; `/branch`.
- **User-list checks** ([CHECKS.md](docs/CHECKS.md)) — each `instructions/*.txt`
  is an ordered list of checks; before an agent finishes "complete" the runtime
  verifies them one-by-one (deterministic where `[[auto:]]`-tagged, else
  model-judged).
- **Conversation inheritance** ([CONTEXT.md](docs/CONTEXT.md)) — each recursive
  agent inherits the full branch conversation (incl. the parent's model output)
  plus a unique purpose; an over-large branch is compressed by a **summarizer
  agent** before children inherit it.
- **Live control** — background-threaded swarms with `/pause` `/resume` `/cancel`
  `/stop-after-current-wave`.

Remaining work is hardening and real-model tuning of the instruction files.

## Configure your models

Every instruction file's first line is `MODEL:`. `<PLACEHOLDER_OLLAMA_MODEL>`
means "fall back to settings". Set a real model in **either** place:

- Per role: edit the `MODEL:` line in e.g. `instructions/coding.txt`.
- Global/role defaults: edit `DEFAULT_*_MODEL` in `settings/main.settings`.

Context size is **auto-detected** from the model — leave `*_NUM_CTX=auto`. The
`MAX_AUTO_NUM_CTX` ceiling (default 16384) caps it so a model's huge native
context doesn't exceed laptop VRAM.

```bash
ollama pull qwen2.5-coder:7b
# then in settings/main.settings:  DEFAULT_MODEL=qwen2.5-coder:7b
```

## Run it (on your laptop, with Ollama)

```bash
ollama serve                       # in another terminal
python -m swarm.main               # interactive chat
python -m swarm.main "build me X"  # one-shot
```

Type to talk to the progenitor; `/ask <msg>` for a raw model line; `/help` for
the full command set. See [`docs/COMMANDS.md`](docs/COMMANDS.md).

> Both `OLLAMA_GPU_ENDPOINT` and `OLLAMA_CPU_ENDPOINT` default to
> `http://localhost:11434` (a single Ollama instance). Point them at separate
> instances only if you actually run two.

## Develop / test (no Ollama needed)

```bash
pip install -r requirements.txt
python -m pytest -q                # 92 tests, all offline via a mock client
python tools/bootstrap_static.py   # regenerate static scaffold (won't clobber edits)
```

## Reality check for low-tier local models

The single biggest risk is tool-call reliability: a quantized 7B model will
sometimes emit malformed `<<tool:>>` blocks. The parser is deliberately
forgiving and the loop feeds corrections back, but if a model proves too
unreliable we may switch to Ollama's schema-constrained output. With one GPU
slot (`MAX_ACTIVE_GPU_AGENTS=1`) the GPU-routed agents serialize while CPU
agents run alongside, so expect minutes of wall-clock for a multi-agent tree.
The finish-gate ([CHECKS.md](docs/CHECKS.md)) is what stops a small model from
"hallucinating" success — it can't finish a coding task without a real file and
a passing validation command.
