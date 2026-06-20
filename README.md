# recursive_local_swarm

A local, chat-driven, **recursively-agentic** LLM swarm that runs on Ollama.

You talk to one **primary agent** (the plan-setter). Once it's satisfied you've
agreed on a plan, it spawns a **council** of specialist agents. The council works
toward the goal and **converges** through rounds of contribution and voting until
every member agrees the work is FINISHED. A **zipper agent** then assembles the
members' final outputs into one deliverable and hands it back up. Any agent that
finds its slice too big can spawn its **own** sub-council, so the swarm goes as
deep as the problem needs.

The runtime is **pure Python standard library** — no third-party packages to
install. `pytest` is only needed to run the tests.

---

## 1. Setup

**Ollama** must be running locally with at least one model pulled:

```
ollama serve                    # if it isn't already running
ollama pull qwen2.5-coder:7b    # or any model you prefer
```

Open `settings/main.settings` and set `DEFAULT_MODEL` to the model you pulled.
That one model is used for every role unless you override a specific role with
`DEFAULT_<ROLE>_MODEL` (e.g. `DEFAULT_PRIMARY_MODEL`, `DEFAULT_CODE_MODEL`).

**Docker** is optional. It's only used to let the coding/testing/optimization/
math agents actually run code in a hardened sandbox. To pre-build the sandbox
image (with many language toolchains baked in) once:

```
python -m swarm.main --initiate
```

Without Docker the swarm still runs; sandbox code-execution simply isn't
available.

---

## 2. Running it

```
python -m swarm.main                 # interactive chat with the primary agent
python -m swarm.main "build me X"    # one-shot: give the goal up front
python -m pytest -q                  # offline tests (mock model, no Ollama/Docker)
```

**Ctrl-C** cancels a running swarm and drops you back to the prompt; **Ctrl-D**
(or Ctrl-C at the empty prompt) quits. Warm sandbox containers are cleaned up on
quit.

---

## 3. What you'll experience

1. **You describe a goal.** The primary agent replies, asking questions and
   shaping a plan with you over as many turns as it takes.
2. **Behind the scenes**, after every one of your messages, the primary quietly
   asks *itself* whether you've actually agreed to start (a hidden check you
   never see). While you're still planning, the answer is no and the chat
   continues normally.
3. **When you agree**, that hidden check flips to yes and the swarm launches. You
   see a running stream of **one-line status notices** in the same chat window,
   for example:

   ```
   [council_0001] council convening (coding, testing, philosophizing) on: build a CSV summariser
   coding started write summariser
   coding (agent_0003) running python in the sandbox…
   coding (agent_0003) sandbox python done — exit 0
   [council_0001] round 1 vote 2-1 (YAY-NAY) — INCOMPLETE — goal: build a CSV summariser
   [council_0001] round 2 vote 3-0 (YAY-NAY) — FINISHED — goal: build a CSV summariser
   [council_0001] council finished — result ready
   result saved to workspace/results/result_0001.md
   ```

4. **The finished result** is printed to the chat **and** saved as its own file
   in `workspace/results/`. You can keep talking afterward (e.g. "now also handle
   TSV") — the primary remembers the *result* it produced and continues from
   there.

These status lines are informational only; they are not part of any agent's
conversation.

---

## 4. The agents

Each agent type is defined by a plain-text instruction file you can edit; the
whole file is that agent's purpose.

| Agent | File | Role |
|-------|------|------|
| primary | `instructions/primary/agent` | The plan-setter you talk to. Asks questions, forms the plan, decides when to spawn. |
| coding | `instructions/coding` | Writes the code. Can run it in the sandbox. |
| testing | `instructions/testing` | Writes and runs tests against the code. |
| optimization | `instructions/optimization` | Improves performance against a measured baseline. |
| math | `instructions/math` | Checks the math/complexity of the work. |
| philosophizing | `instructions/philosophizing` | Judges the work against the *human* intent; flags gaps and unintended consequences. |
| zipper | (no instruction file) | Assembles the council's final outputs into one deliverable. Its instructions live in the zipper process. |

The coding, testing, optimization, and math agents are the only ones with a tool:
the Docker sandbox.

---

## 5. How a council converges

When a council is spawned, every member is given the same inherited conversation
plus its own purpose and specific task, and the convergence loop runs:

1. **Contribute** — each member produces a plan or a finished attempt. Members
   with the sandbox tool may run/test code first and read the output.
2. **Convene** — each member reads everyone *else's* contribution.
3. **Vote** — each member votes `FINISHED` or `INCOMPLETE` from the angle of its
   own role.
4. If **everyone** votes FINISHED, the council is done. Otherwise the collective
   reasoning is fed back and each member chooses to **WAIT** (its part is done)
   or **CONTINUE**. A continuing member either keeps working alone or **spawns
   its own sub-council** to handle the depth — and the loop repeats.

A council never ends in failure; it keeps iterating until unanimous (bounded by a
safety cap so it can't run forever).

**Voting is logged.** Every round prints a `X-X (YAY-NAY)` tally with the status
and the goal, and appends a full record (agent types + individual votes) to
`logs/votes.jsonl` so you can search/track them later.

---

## 6. The zipper (final assembly)

Once a council agrees, the **zipper** receives the conversation that led to the
council plus each member's final output (and nothing of the council's internal
back-and-forth). It writes nothing itself — it issues commands that keep or
splice the existing outputs into one clean document, confirms the arrangement,
and sends it upstream under a `FINISHED OUTPUT` header. Philosophy/notes that read
like LLM chatter are trimmed; the real deliverable is what remains.

---

## 7. Key design principle: ephemeral queries

Some prompts are **queries** — one-shot questions whose *conversation* is thrown
away and whose *result* is what's kept. The hidden confirm check, the spawning
directive request, and the expansion (continue-or-spawn) choice all work this
way: they never clutter an agent's memory. When an agent spawns a sub-council,
only the council's **result** is inserted back into that agent's history, as if
it were the agent's own work. This is what keeps every level's conversation clean
and fluid.

---

## 8. The sandbox

- The **only** official tool, granted to the coding/testing/optimization/math
  agents: run/test code by putting it in a fenced code block.
- Code blocks are **recognised per language** (Python, JS/TS, Ruby, Go, Rust,
  C/C++, Java, PHP, Perl, Lua, R, Julia, Haskell, Bash, SQL, …). Functions split
  across multiple blocks of the same language are run together.
- By default **one warm container is kept running for the whole session**
  (`SANDBOX_REUSE_CONTAINER=true`): it mounts the shared agents root once, and
  every run just `docker exec`s into that agent's subdirectory — so container
  startup is paid once for the session, not per run. It's torn down when you quit.
  Set the flag to `false` for a throwaway `docker run --rm` per execution instead.
  Execution is sequential either way, and each agent still has its own work
  directory.
- It's **hardened**: `--network none`, `--cap-drop ALL`,
  `--security-opt no-new-privileges`, read-only root + small tmpfs,
  memory/CPU/PID limits, and a non-root user baked into the image.
- You're notified in the chat when an agent starts a sandbox run and when it
  finishes (with the exit status).

---

## 9. Long conversations: summarize-on-overflow

If any agent's conversation grows past its model's context budget, the oldest
turns are automatically compressed into a briefing (top-down) while the most
recent turns are kept verbatim. This happens transparently and frees space so a
deep or long-running swarm keeps going. Toggle/tune it with `SUMMARIZE_ON_OVERFLOW`
and `SUMMARIZE_RECENT_FRACTION` in the settings.

---

## 10. Customising behaviour

- **Prompts** — every instruction/query/convergence/zipper file under
  `instructions/` is plain text you can edit. The whole file is the prompt.
  `instructions/primary/confirm` (the hidden readiness check) is yours to word —
  just keep it ending in YES/NO so the parser can read the verdict.
- **Settings** — `settings/main.settings` controls models, per-role context/
  output/temperature, GPU/CPU routing, convergence/recursion bounds, the
  summarizer, the sandbox, and directory locations.
- **Functions** — the `>>...<<` helpers (`functions/*.py`) are real importable
  Python; `swarm/functions.py` re-exports them.

---

## 11. Where things live

```
instructions/
  system                 system-wide prompt (prepended for every role except zipper)
  primary/agent          the primary agent
  primary/confirm        the hidden "has the user agreed?" check
  coding, testing, ...   one file per agent type
  convergence/*          the convergence prompts (initiation, action, convene, vote, …)
  queries/*              ephemeral queries (spawning, expansion)
  zipper/*               the zipper prompts
  functions/*            human-readable explanations of the >>...<< functions
functions/*.py           the real >>...<< functions
swarm/*.py               the runtime
settings/main.settings   configuration
workspace/results/       finished results, one file each
workspace/agents/<id>/   per-agent: conversation.md (full chat) + sandbox files
logs/votes.jsonl         searchable vote log
```

---

## 12. A note on reliability

The orchestration (substitution, convergence ordering, voting/logging, the
hidden confirm, expansion→sub-council recursion, the zipper, summarisation) is
all hard-coded and tested. The *quality* of results depends on your model
following the format instructions — emitting the `AGENT_TYPE: task: explanation`
directives, ending votes with `I vote FINISHED`/`I vote INCOMPLETE`, ending the
confirm check with YES/NO, and so on. A small/quantised model may need a stronger
model for the planning and voting roles.
