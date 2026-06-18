# recursive_local_swarm

A local, chat-driven, recursively-agentic LLM swarm that runs on Ollama. You talk
to a **chat_agent** (the root agent); it decides (per editable instruction files) whether to
answer directly or spawn a recursive swarm of agents that write code, run it in a
sandbox, reconcile each other's work, and report back. Runtime is **pure stdlib**
(no third-party deps).

## Docs

- [`docs/PLAN.md`](docs/PLAN.md) — build status + design decisions
- [`docs/CHECKS.md`](docs/CHECKS.md) — instruction files (how agents follow them)
- [`docs/CONTEXT.md`](docs/CONTEXT.md) — conversation inheritance, purpose, summarizer
- [`docs/COMMANDS.md`](docs/COMMANDS.md) — chat & slash command reference

## What's implemented

Tested offline with a mock model (no Ollama needed):

- **Core loop** — settings/instruction/prompt loaders; model probe (auto context
  size via `/api/show`); per-role model selection from settings; stdlib Ollama
  client; SQLite state; tolerant `<<tool:...>>` parser; unlimited recursive
  spawning.
- **Execution** — path/command/cwd guards (Python force-jails every file write
  into the agent's dir; the agent never picks the location); sandboxed
  `python`/`shell` and persistent terminals behind one `Executor` interface with
  **subprocess and Docker** backends (Docker auto-selected when the daemon is up).
  Tool timeouts come from the agent's call, not settings.
- **Web** — `curl`/`search_web_cache`/`read_cached_page` with an SSRF guard and a
  freshness-based on-disk cache.
- **Reconciliation** — `request_review`/`request_integration`/`request_testing`/
  `request_fix` spawn the matching agent role.
- **Code pipeline** — a spawned `coding_agent` work-unit runs as three models in sequence,
  each fed the previous one's output: **coding_agent → testing_agent → philosopher**, each
  following its own instruction file.
- **Profiling/optimization** — `profile` (cProfile + baseline) and `optimize`
  (sandboxed before/after validation).
- **Scheduler** — stdlib resource monitor (RAM/CPU/VRAM/disk); GPU/CPU agent
  concurrency **measured at startup** (`swarm/calibration.py`), not hand-set;
  parallel agents over a thread-safe shared DB.
- **Memory & branching** — `/remember`/`/forget`/`/memories`; `/branch`.
- **Instruction files** ([CHECKS.md](docs/CHECKS.md)) — each `instructions/*.txt`
  is an ordered list of instructions the agent follows; the model per role is set
  in `settings/main.settings`. Verification is done by spawned checker agents,
  not a runtime gate.
- **Conversation inheritance** ([CONTEXT.md](docs/CONTEXT.md)) — each recursive
  agent inherits the full branch conversation (incl. the parent's model output)
  plus a unique purpose; an over-large branch is compressed by a **summarizer
  agent** before children inherit it.
- **Live display** — one terminal line per active agent that updates in place;
  each agent's conversation is also written to
  `workspace/agents/<id>/logs/conversation.md` in real time.
- **Live control** — background-threaded swarms with `/pause` `/resume` `/cancel`
  `/stop-after-current-wave`.

Remaining work is real-model tuning of the instruction files.

## Reality check for low-tier local models

The biggest risk is tool-call reliability: a quantized 7B model will sometimes
emit malformed `<<tool:>>` blocks. The parser is deliberately forgiving and the
loop feeds corrections back. With recursion unbounded and every code unit
spawning three agents, convergence depends on the instruction files — they are
what make agents finish, defer, or stop spawning. The defense against a model
"hallucinating" success is the spawned checker pipeline (coding_agent → testing_agent →
philosopher), each following its own instruction file.
