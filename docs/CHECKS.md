# Instruction files (user-lists)

Every file in `instructions/` is an ordered list of **instructions** for the
process it is named after. An agent of that role is given these lines and
**follows them** as it works — they are injected into its prompt in order. They
are not evaluated by any separate runtime "gate"; there is no model that reads
them and emits pass/fail. Instructions are instructions; agents follow them.

## Format

```
PURPOSE: <what this process is for>
001. <instruction>
002. <instruction>
...
```

- No `MODEL:` line. The model for each role is set in `settings/main.settings`
  (`DEFAULT_<ROLE>_MODEL`, falling back to `DEFAULT_MODEL`).
- Blank lines and `#` comments are ignored. A leftover `MODEL:` line, if present,
  is accepted and ignored.

## Which files an agent is given

An agent of role R is given, in order: `global.txt`, `safety.txt`,
`progress_reporting.txt`, `finishing.txt`, the role's own file (e.g.
`coding.txt`), and one file per tool it can use (e.g. `python_execution.txt`,
`file_writing.txt`, `terminal_execution.txt`). So put universal rules in the
global files and process-specific rules in the role/tool files.

## Verification is done by agents, not a gate

There is no runtime check that re-reads an agent's lines and decides pass/fail.
Verification happens because work is **spawned through checker agents**, each of
which just follows its own instruction file:

- A spawned **code** work-unit runs as a sequence (see [CONTEXT.md](CONTEXT.md)
  and the pipeline in `swarm/agent_loop.py`):
  1. **code** — follows `coding.txt`: writes the code, works through its
     instructions, runs it.
  2. **code_checker** — follows `code_checking.txt`: inherits the coder's output
     and verifies the code is up to spec / fits the bigger picture.
  3. **philosopher** — follows `philosophizing.txt`: verifies the work meets the
     human-level intent and reports a verdict to the parent.

Each is an ordinary agent with the same machinery; only its instruction file
(its "purpose") differs. To change how any stage behaves, edit its instruction
file. To change which model runs a stage, edit `settings/main.settings`.
