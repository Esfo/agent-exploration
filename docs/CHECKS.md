# Instruction files (the agent grammar)

Every file in `instructions/` describes one process. Files have **no `.txt`
extension** (`instructions/<name>`). The model for each role is set in
`settings/main.settings` (`DEFAULT_<ROLE>_MODEL`, falling back to `DEFAULT_MODEL`),
never in the file. Blank lines and `#` comments are ignored.

## Format — PURPOSE / INPUT / VERIFY / FINISH

A primary agent file is an executable program (`swarm/instruction_program.py`):

```
PURPOSE: <who this agent is, and what it does within the convergence>
INPUT:
001. <plain guidance on how to do the work>
002. <...>
VERIFY: <a yes/no question gating completion>
    YES: FINISH
    NO: VERIFY: <a deeper yes/no question diagnosing why>
        YES: <feedback prompt — loops back>
        NO: <feedback prompt — loops back>
        ?: Please answer YES or NO.
    ?: I didn't catch that — please answer YES or NO.
FINISH: I vote FINISHED
```

- `PURPOSE:` frames the agent. `INPUT:` is hard-substituted by the runtime with the
  agent's actual input; any text after `INPUT:` is appended to that message.
- A `VERIFY:` asks the model a yes/no question. Python matches the answer against
  the branch labels; the matched branch's action runs — `FINISH` (satisfied), a
  nested `VERIFY:` (recursive diagnosis), or a feedback prompt (loops back). The
  final `?` branch is the wildcard, run when nothing matched.
- `FINISH:` at the top level is the terminal; whatever follows it is the expected
  output that ends the loop (e.g. the convergence vote `I vote FINISHED`).

Because every agent acts inside a **convergence** (see below), the VERIFY loop
doubles as the agent's vote: when `INSTRUCTION_PROGRAM_VOTING=true`, the runtime
executes the agent's program to decide its FINISHED/INCOMPLETE vote. Roles whose
file is not an executable program fall back to a free-form vote.

Shared/tool-guidance files (`global`, `safety`, `progress_reporting`,
`command_questioning`, `sandboxing`, `resource_pressure`) remain plain
`PURPOSE:` + numbered guidance — they are context, not standalone agents.

## Which files an agent is given

An agent of role R is given, in order: `global.txt`, `safety.txt`,
`progress_reporting.txt`, `finishing.txt`, the role's own file (e.g.
`coding_agent`), and one file per tool it can use (e.g. `python_execution.txt`,
`file_writing.txt`, `terminal_execution.txt`). So put universal rules in the
global files and process-specific rules in the role/tool files.

## Verification is done by agents, not a gate

There is no runtime check that re-reads an agent's lines and decides pass/fail.
Verification happens because work is **spawned through checker agents**, each of
which just follows its own instruction file:

- A spawned **coding_agent** work-unit runs as a sequence (see [CONTEXT.md](CONTEXT.md)
  and the pipeline in `swarm/agent_loop.py`):
  1. **coding_agent** — follows `coding_agent`: writes the code, works through its
     instructions, runs it.
  2. **testing_agent** — follows `testing_agent`: inherits the coder's output
     and verifies the code is up to spec / fits the bigger picture.
  3. **philosopher** — follows `philosophizing.txt`: verifies the work meets the
     human-level intent and reports a verdict to the parent.

Each is an ordinary agent with the same machinery; only its instruction file
(its "purpose") differs. To change how any stage behaves, edit its instruction
file. To change which model runs a stage, edit `settings/main.settings`.
