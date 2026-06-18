# Chat & slash command reference

Run `python -m swarm.main` for the interactive REPL, or
`python -m swarm.main "your goal"` for one-shot.

## Talking to the system

- **Bare text** → goes to the **chat_agent** (the root agent), which decides for itself
  (per its instruction checks) whether to answer directly or spawn a swarm. The
  runtime never force-spawns.
- **`/ask <message>`** → a raw, tool-less single-turn line straight to the model
  (no agent loop, no gate). For sanity-checking the model itself.

Swarms run in a **background thread**, so the prompt stays responsive while one
runs — control and status commands work mid-swarm.

## Live control

| command | effect |
|---------|--------|
| `/pause` | running agents hold before their next step |
| `/resume` | resume paused agents |
| `/cancel [agent_id]` | cancel the whole swarm, or one agent, at its next checkpoint |
| `/stop-after-current-wave` | finish running agents but spawn no new ones |

(Cooperative — checked at safe points in the agent loop; nothing is killed mid-write.)

## Status

| command | shows |
|---------|-------|
| `/status`, `/progress` | swarm status + agent state breakdown |
| `/agents` | all agents in the last swarm |
| `/tree` | the recursive agent tree |
| `/active` `/queued` `/completed` `/failed` `/blocked` | agents by status |
| `/models` | model used per role |
| `/terminals` `/sandboxes` | open terminals / sandboxes |
| `/profile` `/optimization` | profiling / optimization reports |
| `/show-cache` | cached web pages |

## Detail

| command | shows |
|---------|-------|
| `/show <agent_id>` | one agent's task, model, status, result |
| `/show-log <agent_id>` | an agent's **raw model output + every tool call** (debugging) |
| `/show-files <agent_id>` | file events for an agent |
| `/show-checklist <agent_id>` | an agent's checklist items |
| `/show-terminal <terminal_id>` | commands run in a terminal + cwd-guard status |
| `/show-sandbox <sandbox_id>` | a sandbox's backend/network/status |
| `/show-settings` | key runtime settings |

## Memory & branching

| command | effect |
|---------|--------|
| `/memories` | list stored memories (on/off) |
| `/remember [scope=…] <text>` | add a memory (default scope `global`) |
| `/forget <memory_id>` | disable a memory |
| `/branch <swarm_id> [note]` | fork a swarm (copies goal + root messages) |
| `/branches` | list swarms/branches |

## Other

| command | effect |
|---------|--------|
| `/set KEY VALUE` | live in-memory settings override (not persisted) |
| `/help` | this list |
| `/quit`, `/exit` | leave |

When debugging model behavior, `/show-log <agent_id>` is the key tool — it prints
exactly what the model emitted and how each tool call resolved.
