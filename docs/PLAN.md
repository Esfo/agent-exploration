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

### Control / chat completeness ✅
- [x] Background-threaded swarm execution; REPL stays responsive
- [x] Live control: /pause /resume /cancel [agent_id] /stop-after-current-wave
      (cooperative checkpoints in the agent loop)
- [x] Full slash command set incl. /queued /completed /blocked and
      /show-files /show-checklist /show-terminal /show-sandbox /show-log
- [x] /ask raw model line; /set live override
- [x] Docker image preflight (checks/pull on startup, non-fatal fallback)

### Prototype 6 — branching + memory + summarization ✅
- [x] Context summarization when over token budget (keep head + recent, condense middle)
- [x] Memory store + enable/relevance toggles, injected into context
- [x] Conversation/swarm branching (copy goal + root messages, independent future)

### Prototype 7 — convergence + voting ✅ (wired into spawn path)
- [x] `swarm/convergence.py`: response→vote rounds over a spawned agent group
- [x] Spec-worded prompts (initiation, "plan or execute", the vote ASK, the
      INCOMPLETE consolidation feedback) sourced in `instructions/convergence`
- [x] Vote tally by text match on "I vote FINISHED"/"I vote INCOMPLETE"
      (final-word wins), unanimity gate, `CONVERGENCE_MAX_ROUNDS` cap
- [x] Per-round vote logging to `logs/convergence.jsonl` + chat summary line
- [x] Wired into `_run_children`: a spawned group of >1 agent runs its work, then
      converges (group vote) before returning upward; verdict folded into the
      summary the parent receives (gated by `CONVERGENCE_ENABLED`)
- [x] Hand the converged result off to a `zipper_agent` (finalizer): on a FINISHED
      vote, `swarm/zipper.py` runs a YES/NO gate per artifact, copies approved
      deliverables into `PROJECT_DIR`, and writes/updates an `INTEGRATED.md`
      manifest. Gated by `ZIPPER_ENABLED`.
- [x] Convergence **never ends INCOMPLETE**: a non-unanimous round escalates and
      the loop continues; a safety bound force-resolves (recorded) so it can't run
      unbounded. Two escalation forms wired in `agent_loop`:
      - (a) **add peer agents** — the required complementary roles (a coding agent
        implies testing + philosophy peers) are added to the group
      - (b) **dissenter sub-swarm** — a dissenting agent can take its job over as
        its own swarm; the sub-swarm converges and the zipper moves its finalized
        work back **into that agent's directory**, bubbling up one level at a time
- [x] Zipper **moves** (not copies) finalized work into categorized destination
      dirs (`code/ docs/ research/ math/ reports/ notes/`) chosen by role then
      extension, with a minimal "here's the code / here's the docs/…" manifest;
      `target_dir` lets each swarm level finalize into its own area
- [ ] Response phase optionally routed through full `run_agent` (real tool use)

### Prototype 8 — instruction-program grammar ✅
- [x] `swarm/instruction_program.py`: parser + executor for the
      PURPOSE/INPUT/VERIFY/FINISH grammar (nested recursive VERIFY, `?` wildcard,
      FINISH terminal), model-agnostic `ask()` runner
- [x] All 21 primary agent files rewritten into the grammar, tied to convergence
      (each VERIFY loop ends in `FINISH: I vote FINISHED`)
- [x] `INSTRUCTION_PROGRAM_VOTING`: convergence executes an agent's program to
      decide its vote, falling back to free-form for non-program files
- [x] Tests: `test_instruction_program.py` (6) + program-voting convergence tests
- [x] Hard-substitute `INPUT:` with the real upstream input in the runner
      (`Program.render_input` + `system_text` + `messages_to_text`); convergence
      frames each program-voting agent with its PURPOSE+guidance and a substituted
      INPUT built from the shared context
- [x] `bootstrap_static.py` no longer carries instruction bodies — instruction
      files are authored/version-controlled; bootstrap validates them against
      `INSTRUCTION_NAMES` and flags any missing

### Naming / conventions
- Root/chat-facing role renamed **`progenitor` → `chat_agent`** (instruction file
  `instructions/chat_agent`); settings key `INSTRUCTION_PROGENITOR` kept internal.
- Worker roles: **`code` → `coding_agent`**, **`code_checker` → `testing_agent`**.
- New role **`zipper_agent`** (finalizer).
- **Instruction files no longer use a `.txt` extension** (`instructions/<name>`).

## Beyond the spec — owner design corrections

The spec framed some things in ways the system owner later corrected. These are
now the canonical behaviors (see linked docs):

### User-lists are instructions the agent follows ✅ — see [`CHECKS.md`](CHECKS.md)
- Each `instructions/*.txt` is an ordered list of **instructions** for its named
  process, injected into the agent's prompt and followed in order. There is NO
  runtime gate that re-reads them as pass/fail. Verification is done by spawning
  checker agents (testing_agent, philosopher) that follow their own files.
- Instruction loading: an agent is given global + safety + progress + finishing
  + its role file + one file per usable tool.
- The model for a role is set in settings/main.settings, not the instruction file.

### Conversation inheritance + unique purpose ✅ — see [`CONTEXT.md`](CONTEXT.md)
- Each recursive agent inherits the **full conversation** of the branch it was
  spawned from (including the parent's model outputs), then receives its own
  **unique purpose**. Only the purpose is unique; the history is shared.
  (`swarm/context_builder.build_messages`, `agent_loop._purpose_text`)

### Spawn-inherit overflow → summarizer agent ✅ — see [`CONTEXT.md`](CONTEXT.md)
- If a branch conversation is too large to inherit, a **summarizer agent** (own
  role + `instructions/summarizing.txt`) compresses the first `SUMMARIZE_FRACTION`
  (60%); the briefing is prepended to the rest for the children.
  (`agent_loop._run_summarizer`)

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
5. **Parallel agents on one GPU.** Inference is gated by GPU/CPU semaphores
   (`MAX_ACTIVE_GPU_AGENTS` / `MAX_ACTIVE_CPU_AGENTS`); children run thread-per-
   child over a thread-safe shared SQLite connection. With one GPU slot the
   GPU-routed work serializes while CPU agents run alongside.
6. **No hardcoded anti-loop / divide-or-defer.** That behavior lives in the
   user-list checks (the model decides to split or defer), not in Python.

## Runtime has no third-party dependencies
Pure stdlib (`urllib`, `sqlite3`, `json`). `pytest` is dev-only.
