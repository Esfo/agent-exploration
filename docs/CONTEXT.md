# Context model: inheritance, purpose, and summarization

How an agent's prompt is assembled, what recursive children inherit, and what
happens when a branch gets too big.

## What an agent sees

Each model call for an agent is assembled as (`swarm/context_builder.build_messages`):

```
[ system  ] role instructions  (its instruction files, followed in order)
[ user…   ] INHERITED CONVERSATION  (the full thread of the branch it came from)
[ user    ] THIS AGENT'S PURPOSE     (unique per agent; + any relevant memories)
[ user/…  ] its own WORKING turns    (accumulated as it acts)
```

- The **system** message is the agent's role + tool + safety instruction files
  (see [CHECKS.md](CHECKS.md)).
- The **inherited conversation** is the full message history of the branch that
  spawned it — *including the parent's assistant (model) outputs*, recursively
  up the chain. Children are not isolated; they read what their ancestors said
  and did.
- The **purpose** is the one thing unique to each agent, e.g.:
  > *This is your purpose: ROLE: coding_agent. You are an individual agent (agent_0007)
  > working on #4 within the context of the conversation above. Your specific
  > task: "…". It is your job to complete this and return your result to your
  > parent branch (agent_0003). Work only in … Now follow your instruction
  > checks below.*

So: **history is always inherited; only the purpose is unique.**

## How inheritance is threaded

When an agent spawns children (`agent_loop.run_agent`):

```
branch_conversation = inherited + [purpose] + own_working_history
# (optionally summarized — see below)
for each child: run_agent(child_id, inherited_history=branch_conversation)
```

The root agent has no parent, so its inherited history is empty — it gets only
its system prompt and its purpose (the user's request).

The purpose message is **pinned** during token-budget summarization
(`token_budget.summarize_to_fit`) so an agent never loses its own purpose even
when older context is compressed.

## Spawn-inherit overflow → a summarizer agent

Because every level inherits everything, context grows with depth. If a branch
conversation is too large for a child to inherit, the runtime spawns a dedicated
**summarizer agent** instead of silently truncating (`agent_loop._run_summarizer`):

1. **Trigger** (`_needs_summary`): the branch conversation exceeds the parent's
   context budget (`num_ctx − num_predict − margin`), or an explicit
   `SUMMARIZE_SPAWN_MAX_TOKENS` cap.
2. A real agent with role `summarizer` is created (shows in `/agents`, `/tree`),
   using `DEFAULT_SUMMARIZER_MODEL` and the checks in
   `instructions/summarizing.txt`.
3. It compresses the **first `SUMMARIZE_FRACTION`** (default 60%) of the
   conversation into a briefing.
4. The briefing is **prepended** to the remaining 40%, and that becomes the
   inherited history for the children:
   `[SUMMARY OF EARLIER CONVERSATION] … + last 40% verbatim`.
5. If the summarizer model is unavailable, a deterministic recap is used so a
   spawn never fails.

### Settings

| key | meaning |
|-----|---------|
| `SUMMARIZE_ON_SPAWN_OVERFLOW` | enable the summarizer-on-spawn path |
| `SUMMARIZE_FRACTION` | fraction of the conversation to compress (default 0.6) |
| `SUMMARIZE_SPAWN_MAX_TOKENS` | explicit trigger cap; `0` = derive from budget |
| `DEFAULT_SUMMARIZER_MODEL`, `SUMMARIZER_NUM_CTX/PREDICT/TEMPERATURE` | the summarizer's model config |
| `MAX_AUTO_NUM_CTX`, per-role `*_NUM_CTX` | the context budgets that determine when overflow happens |

## Per-call token budgeting (separate safety net)

Independently of the summarizer agent, every individual model call passes through
`summarize_to_fit`: if the assembled prompt still exceeds the budget, the oldest
middle messages are condensed inline (system + purpose + recent turns kept). This
is the deterministic floor; the summarizer agent is the richer, model-driven path
used specifically at spawn time.
