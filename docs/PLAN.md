# Development plan

Derived from the master spec (`master_spec_001`). The spec is the source of
truth for behavior; this file tracks build status and records design decisions
that deviate from or sharpen the spec.

## Prototype status

### Prototype 1 — core loop ✅ (done, offline-tested)
- [x] Directory structure + static scaffold (`tools/bootstrap_static.py`)
- [x] `settings/main.settings` + loader
- [x] Instruction/prompt files + loader (`MODEL:` aware)
- [x] Model probe (auto context/size detection via `/api/show`)
- [x] Model selector (resolution order, routing, ctx/predict/temp)
- [x] Ollama client (stdlib only)
- [x] SQLite state (full schema)
- [x] Tolerant `<<tool:>>` parser
- [x] Context packet builder + token budget guard
- [x] Tools: `spawn_agents`, `report_progress`, `finish`
- [x] Agent loop + recursive spawning + recursion ceilings
- [x] Progress/event bus + weighted completion
- [x] Chat REPL + slash commands

### Prototype 2 — execution ✅
- [x] `runtime_guards`: path_guard (force-jail placement), command_guard, cwd_guard
- [x] Command questioning enforcement (hard Python checks, not model self-report)
- [x] Executor interface + subprocess backend (rlimits, timeout, output caps)
- [x] Docker backend behind the same Executor interface (real isolation)
- [x] File tools: list/read/write/append/delete (jailed by Python, soft delete)
- [x] Sandboxed `python` + `shell` tools
- [x] Persistent `open_terminal` / `terminal_command` / `close_terminal` + cwd_guard

### Prototype 3 — web + reconciliation ✅
- [x] Web fetch/cache tool + web_guard (SSRF/private-IP/metadata blocking)
- [x] curl / search_web_cache / read_cached_page
- [x] review / integration / tester / fixer roles via request_* tools

### Prototype 4 — profiling + optimization ✅
- [x] profile tool (cProfile wrap, baseline runtime, top bottlenecks)
- [x] optimize tool (before/after, sandboxed validation, requires profiling first)

### Prototype 5 — scheduler + routing + richer chat ✅
- [x] CPU/GPU routing per role (model_selector + endpoints)
- [x] Richer slash commands + spec-33 final summary
- [x] Resource monitor: RAM/CPU/VRAM/disk sampling (stdlib) + pressure checks
- [x] Scheduler: GPU/CPU inference slots + backpressure (queue under pressure)
- [x] Parallel agent execution (thread-per-child) + thread-safe shared DB

### Prototype 6 — branching + memory + summarization ✅
- [x] Context summarization when over token budget (keep head + recent, condense middle)
- [x] Memory store + enable/relevance toggles, injected into context
- [x] Conversation/swarm branching (copy goal + root messages, independent future)

## Design decisions / deviations from spec

1. **Tool protocol:** keeping the spec's free-text `<<tool:>>` blocks, but the
   parser is tolerant (strips fences, repairs trailing commas, recovers missing
   close tags). Fallback to Ollama schema-constrained output remains on the
   table if a target model proves too unreliable in practice.
2. **Context size is auto-detected**, not hard-coded. `*_NUM_CTX=auto` triggers
   a `/api/show` probe; `MAX_AUTO_NUM_CTX` caps it for laptop VRAM. Spec's fixed
   numbers (32768 etc.) became `auto`.
3. **Recursion ceilings default to finite** (`MAX_RECURSION_DEPTH=3`,
   `MAX_TOTAL_AGENTS_PER_SWARM=20`) during bring-up instead of the spec's
   `unlimited`, to prevent runaway swarms from weak planner models. Set to
   `unlimited` once convergence is proven.
4. **Command safety is enforced in Python, not by the model.** The model-facing
   command questionnaire is guidance; the real boundary (Prototype 2) is the
   sandbox + `command_guard`. The model's self-assessment is never trusted as a
   security control.
5. **Execution is mostly sequential** on one GPU (`MAX_ACTIVE_GPU_AGENTS=1`).
   Prototype 1 runs agents in-process, depth-first; the async scheduler is
   Prototype 5.

## Runtime has no third-party dependencies
Pure stdlib (`urllib`, `sqlite3`, `json`). `pytest` is dev-only.
