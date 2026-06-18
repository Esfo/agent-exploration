# Instruction files (the agent grammar)

Every file in `instructions/` describes one process. Files have **no `.txt`
extension** (`instructions/<name>`). The model for each role is set in
`settings/main.settings` (`DEFAULT_<ROLE>_MODEL`, falling back to `DEFAULT_MODEL`),
never in the file. Blank lines and `#` comments are ignored.

## Format — PURPOSE / INPUT / VERIFY

An instruction file is a small logical machine, not a list of bullet points. It is
read in order: `PURPOSE` sets the agent up, `INPUT:` is where the runtime injects
the agent's input, and the `VERIFY` tree asks the model specific yes/no questions
and branches on the answer. There are **no numbered lines** and nothing is "told"
to the model line by line.

```
PURPOSE: <prose: who this agent is, its job, and the mindset it works in>
INPUT:
VERIFY: <a yes/no question that gates completion>
    YES: FINISH
    NO: VERIFY: <a deeper yes/no question that diagnoses why not>
        YES: <what to do, then it loops back to re-check>
        NO: <what to do, then it loops back to re-check>
        ?: Please answer YES or NO.
    ?: I didn't catch that — please answer YES or NO.
```

- `PURPOSE:` is prose. It is the one thing that frames the agent — not a place to
  dump instructions. Everything procedural lives in the `VERIFY` tree.
- `INPUT:` is hard-substituted by the runtime with the agent's actual upstream
  input; any text after `INPUT:` on the same line is appended to that message.
- `VERIFY:` asks the model a yes/no question. Python matches the answer against the
  branch labels and runs the matched branch: `FINISH` (the check is satisfied — the
  terminal of the tree), a nested `VERIFY:` (recursive diagnosis), or an
  instruction that then loops back to re-ask. The final `?` branch is the wildcard,
  run when no label matched. `FINISH` is a leaf of the tree — it is never a forced
  literal the model has to emit.

A swarm agent's verify tree reaching `FINISH` is what the runtime reads as that
agent being satisfied; when `INSTRUCTION_PROGRAM_VOTING=true` that drives its
convergence vote. Files with no `VERIFY` (e.g. `chat_agent`, `zipper_agent`, and
the shared rule files `global`/`safety`/`progress_reporting`/`command_questioning`/
`sandboxing`/`resource_pressure`) are just `PURPOSE` prose — context, not a loop.

## Which files an agent is given

An agent of role R is given, in order: `global`, `safety`, `progress_reporting`,
`finishing`, the role's own file (e.g. `coding_agent`), and one file per tool it
can use (e.g. `python_execution`, `file_writing`, `terminal_execution`). So put
universal rules in the global files and process-specific rules in the role/tool
files.

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
  3. **philosopher** — follows `philosophizing`: verifies the work meets the
     human-level intent and reports a verdict to the parent.

Each is an ordinary agent with the same machinery; only its instruction file
(its "purpose") differs. To change how any stage behaves, edit its instruction
file. To change which model runs a stage, edit `settings/main.settings`.
