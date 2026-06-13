# User-list checks (finish-gate)

Every file in `instructions/` is a **user-list**: an ordered list of *checks*
for the process the file is named after. They are not just prose injected into
the prompt (though the model does see them as it works) — they are **verified
one-by-one before an agent may finish "complete".**

## How a finish is gated

When an agent emits `finish` with `status: "complete"`, the runtime:

1. Gathers the checks that apply to that agent — `global.txt`, `safety.txt`,
   `progress_reporting.txt`, `finishing.txt`, the role's own file (e.g.
   `coding.txt`), **and** one file per tool the agent can use (e.g.
   `python_execution.txt`, `file_writing.txt`, `terminal_execution.txt`).
2. Walks them **in order**. Each check is judged:
   - **deterministically** if it carries an `[[auto:KEY]]` tag, or
   - **by the model** otherwise.
3. On the **first failing check**, the finish is blocked and the agent is told
   which check failed and why. It then fixes it, decides it needs a separate
   swarm (and spawns), or finishes `blocked` with a reason.
4. After `MAX_GATE_ATTEMPTS` failed attempts, the agent is finished `blocked`
   automatically, naming the failing check.

`status: "blocked"` / `"failed"` are **not** gated — an honest deferral always
passes through.

Controlled by settings: `CHECK_GATE_ENABLED`, `CHECK_GATE_MODEL_EVAL`,
`MAX_GATE_ATTEMPTS`.

## Writing a check line

```
NNN. <a statement that is TRUE when the process was done correctly> [[auto:KEY]]
```

- The text is what the model is judged against (and reads as guidance). Phrase
  it as something verifiable, e.g. *"A validation command was actually run."*
- The `[[auto:KEY]]` suffix is **optional**. If present and `KEY` is a built-in
  deterministic check, the runtime evaluates it from recorded facts (files,
  commands, exit codes) instead of asking the model. The tag is stripped from
  what the model sees.
- Untagged lines are judged by the model (PASS/FAIL with a reason). If the model
  can't return a parseable verdict, the line defaults to PASS — so **deterministic
  `[[auto:]]` checks are the reliable gate**; use them for anything that must
  hold.

## Built-in deterministic checks

| KEY | passes when… |
|-----|--------------|
| `created_a_file` | the agent created or modified ≥1 file |
| `validation_passed` | a `python`/`shell`/terminal command by this agent exited 0 |
| `tests_present` | the agent created a `test_*.py` / `*_test.py` file |
| `cwd_clean` | every terminal command stayed inside the jail |
| `no_failed_commands` | no terminal command exited non-zero |

Add more by registering a function in `swarm/checks.py` (`@_auto("key")`).

## The divide-or-defer pattern

A check can ask the agent to make the call, e.g.:

```
007. If the task cannot be completed correctly, does this require a separate
     agent swarm, or should it be deferred?
```

When such a check (or any failing check) sends the agent back, it can respond by
`spawn_agents` (divide) or `finish` `blocked` (defer). This is the divide-or-defer
behavior — expressed entirely in the user-lists, not hardcoded.
