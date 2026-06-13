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

### Prototype 2 — sandboxed execution ⬜
- [ ] Sandbox manager + Docker backend + mount policies
- [ ] `runtime_guards`: cwd_guard, path_guard, command_guard
- [ ] Command questioning enforcement (hard Python checks, not model self-report)
- [ ] Tools: `open_terminal`, `terminal_command`, `python`, `shell`, file tools

### Prototype 3 — web + reconciliation ⬜
- [ ] Web fetch/cache tool + guards
- [ ] Review / integration / tester / fixer agents

### Prototype 4 — profiling + optimization ⬜
### Prototype 5 — scheduler + CPU/GPU routing + richer /progress + /tree ⬜
### Prototype 6 — branching + memory toggles + context summarization ⬜

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
