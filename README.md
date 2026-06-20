# recursive_local_swarm

A local, chat-driven, recursively-agentic LLM swarm that runs on Ollama. You
talk to a **primary agent** (the plan-setter); once you agree on a plan it spawns
a **council** of agents that converge on a finished answer, hands the result to a
**zipper agent** for final assembly, and returns it. Runtime is pure stdlib
(no third-party deps); `pytest` is dev-only.

## How it works

```
you ──▶ primary agent ──(plan, then "spawn agents?")──▶ council
                                                          │
                            convergence loop: response ─▶ test ─▶ convene ─▶ vote
                                                          │            │
                                  (any member may EXPAND ─▶ SPAWN a sub-council)
                                                          ▼
                                          unanimous FINISHED ─▶ zipper ─▶ result
```

- **Primary agent** (`instructions/primary/agent`) — takes a goal, asks
  questions, forms a plan, and asks the hard-coded *"Would you like me to spawn
  agents to complete this task?"*. A yes (parsed in Python) triggers the
  `>>SPAWNING<<` query and starts a council.
- **Convergence** (`swarm/convergence.py`, prompts in
  `instructions/convergence/`) — the hard-coded loop. Each member is framed with
  `INITIATION + PURPOSE + TASK + ACTION`, contributes (tool-bearing members can
  run code in the sandbox first), then everyone reads each other's work
  (`CONVENE`) and votes. A non-unanimous round feeds back the reasoning and lets
  each member WAIT or CONTINUE; a continuing member can work alone or SPAWN its
  own sub-council. It loops until every member votes FINISHED.
- **Zipper** (`swarm/zipper.py`, prompts in `instructions/zipper/`) — assembles
  the members' final outputs into one document via `RETAIN`/`INSERT` commands,
  confirms it, and returns it with a `FINISHED OUTPUT` header.

## The `>>ARROW<<` substitution engine

`swarm/substitution.py` is the chat parser that ties instruction files, queries,
and functions together. Every `>>NAME<<` marker is resolved (recursively)
against a `Context`:

- **values** — `>>AGENT_TYPE<<`, `>>TASK<<`, `>>TASK_TRUNCATED<<`, `>>INHERITED_GOAL<<`
- **files** — `>>PURPOSE<<`, `>>SPAWNING<<`, `>>EXPANSION<<`, `>>CONVERGENCE_VOTE<<`, `>>INITIATION<<`
- **functions** — `>>LIST_AGENT_TYPES<<`, `>>LIST_TOOLS<<`, `>>COUNCIL_RHETORIC<<`,
  `>>DOCUMENT_DISPLAY<<`, `>>FINAL_OUTPUT<<`, `>>RETURN_OUTPUT<<`. Each is real
  Python living in its own `instructions/functions/<NAME>` file (explanation as
  comments + the function); `swarm/functions.py` loads and calls them.

## Voting & logging

Each council round prints a one-line `X-X (YAY-NAY)` tally with the status
(FINISHED/INCOMPLETE) and the inherited goal, and appends a full record (agent
types + individual votes) to `logs/votes.jsonl` for later search.

## Tools & sandbox

The only official tool is the **Docker sandbox** for running/testing code,
granted to the coding/testing/optimization/math agents. The sandbox is hardened
(`--network none`, `--cap-drop ALL`, `--security-opt no-new-privileges`,
read-only root + tmpfs, memory/cpu/pids limits, non-root user in the image).
Code blocks are recognised per language (`swarm/functions.py`,
`swarm/sandbox/runner.py`).

Build the hardened multi-language image once:

```
python -m swarm.main --initiate
```

## Run

```
python -m swarm.main                 # interactive chat with the primary agent
python -m swarm.main "build me X"    # one-shot goal
python -m pytest -q                  # offline tests (mock model, no Ollama)
```

Set your model in `settings/main.settings` (`DEFAULT_MODEL`, optional per-role
`DEFAULT_<ROLE>_MODEL`).
