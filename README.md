# recursive_local_swarm

A local, chat-driven, recursively-agentic LLM swarm that runs on Ollama. You chat
with a **progenitor** agent; it decomposes the task, recursively spawns child
agents, and reports progress back to chat. All code/command execution is designed
to run sandboxed (sandbox layer lands in Prototype 2).

This repo implements the system described in the master spec. See
[`docs/`](docs/) for the full spec and the development plan.

## Status — Prototype 1 (core loop)

Implemented and tested offline (mock model, no Ollama required):

- `settings/main.settings` loader with typed access (`swarm/settings.py`)
- Plaintext instruction + prompt file loader, `MODEL:` line aware (`swarm/instructions.py`)
- **Model probe** — auto-detects a model's native context length and size via
  Ollama `/api/show`, cached in `runtime/config_cache.json` (`swarm/model_probe.py`)
- Per-role model selection with the spec's resolution order (`swarm/model_selector.py`)
- Stdlib-only Ollama client (`swarm/ollama_client.py`)
- SQLite state store, full spec schema (`swarm/db.py`, `swarm/schema.sql`)
- Tolerant `<<tool:...>>` parser that recovers from the malformed JSON small
  models produce (`swarm/tool_parser.py`)
- Agent loop with recursive spawning, depth/agent ceilings, progress + finish
  (`swarm/agent_loop.py`)
- Chat REPL with slash commands (`swarm/chat_interface.py`, `swarm/main.py`)

**Prototypes 2–4 added** (see [`docs/PLAN.md`](docs/PLAN.md)):
- **Execution:** path/command/cwd guards; file tools (Python force-jails every
  write into the agent dir — the agent never picks the location); sandboxed
  `python`/`shell`; **subprocess and Docker** backends behind one `Executor`
  interface (Docker auto-selected when the daemon is up); persistent
  `open_terminal`/`terminal_command` sessions with enforced cwd.
- **Web:** `curl`/`search_web_cache`/`read_cached_page` with an SSRF guard
  (blocks localhost/private/metadata) and on-disk freshness-based cache.
- **Reconciliation:** `request_review`/`request_integration`/`request_testing`/
  `request_fix` spawn the matching agent role.
- **Profiling/optimization:** `profile` (cProfile + baseline) and `optimize`
  (sandboxed before/after validation).

Not yet built: resource scheduler/backpressure, parallel execution, and
conversation branching + memory toggles (Prototypes 5–6).

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

Slash commands: `/status` `/progress` `/agents` `/tree` `/models`
`/show <agent_id>` `/show-settings` `/help` `/quit`.

> The runtime expects a GPU endpoint (`OLLAMA_GPU_ENDPOINT`, default :11434) and
> a CPU endpoint (`OLLAMA_CPU_ENDPOINT`, default :11435). If you run a single
> Ollama instance, point both at :11434.

## Develop / test (no Ollama needed)

```bash
pip install -r requirements.txt
python -m pytest -q                # 19 tests, all offline via a mock client
python tools/bootstrap_static.py   # regenerate static scaffold (won't clobber edits)
```

## Reality check for low-tier local models

The single biggest risk is tool-call reliability: a quantized 7B model will
sometimes emit malformed `<<tool:>>` blocks. The parser is deliberately
forgiving and the loop feeds corrections back, but if a model proves too
unreliable we may switch to Ollama's schema-constrained output. One laptop GPU
serves ~one model at a time (`MAX_ACTIVE_GPU_AGENTS=1`), so the swarm runs mostly
sequentially — expect minutes of wall-clock for a multi-agent tree.
