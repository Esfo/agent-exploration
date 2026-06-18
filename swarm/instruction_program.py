"""Instruction-program grammar: PURPOSE / INPUT / VERIFY / FINISH.

This is the executable form of an instruction file, following the testing_agent
example. A file looks like:

    PURPOSE: <who this agent is, and what it does within the convergence>
    INPUT:
    <optional plain guidance lines on how to do the work>
    VERIFY: <a yes/no question gating completion>
        YES: FINISH
        NO: VERIFY: <a deeper yes/no question diagnosing why>
            YES: <feedback prompt — loops back>
            NO: <feedback prompt — loops back>
            ?: <re-ask prompt>
        ?: <re-ask prompt>
    FINISH: I vote FINISHED

Semantics (from the spec):
- ``PURPOSE:`` frames the agent. ``INPUT:`` is hard-substituted by the runtime with
  the agent's actual input; any text after ``INPUT:`` is appended to that message.
- A ``VERIFY:`` asks the model a yes/no question. Python matches the answer
  (case-insensitively) against the branch labels. The matched branch's action runs:
    * ``FINISH`` (optionally ``FINISH: <expected>``) — the verify is satisfied.
    * a nested ``VERIFY:`` — a recursive diagnosis, after which we re-evaluate.
    * any other text — a feedback/re-ask prompt; the verify then loops back.
- The final branch is always ``?`` (the wildcard): it runs when no label matched,
  re-prompting and looping back to the top of the verify.
- ``FINISH:`` at the top level is the terminal success; whatever follows it is the
  expected output that ends the loop and lets the agent move on (e.g. its vote).

The runner is model-agnostic: it takes an ``ask(prompt) -> str`` callable, so it is
deterministic and unit-testable, and in the runtime ``ask`` is a model call.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

WILDCARD = "?"


# ----- AST -----

@dataclass
class Finish:
    expected: str = ""


@dataclass
class Prompt:
    text: str


@dataclass
class Verify:
    question: str
    branches: list["Branch"] = field(default_factory=list)

    def branch_for(self, answer: str) -> "Branch | None":
        """The first non-wildcard branch whose label matches the answer."""
        for b in self.branches:
            if b.label == WILDCARD:
                continue
            if _label_matches(b.label, answer):
                return b
        return None

    def wildcard(self) -> "Branch | None":
        for b in self.branches:
            if b.label == WILDCARD:
                return b
        return None


@dataclass
class Branch:
    label: str
    action: object  # Finish | Verify | Prompt


@dataclass
class Program:
    purpose: str = ""
    input_suffix: str = ""
    guidance: list[str] = field(default_factory=list)
    steps: list[object] = field(default_factory=list)  # Verify | Finish, in order

    @property
    def is_executable(self) -> bool:
        return bool(self.steps)


def _label_matches(label: str, answer: str) -> bool:
    """Yes/no style match: the label appears as a whole word in the answer, or the
    answer starts with it. Case-insensitive."""
    a = (answer or "").strip().lower()
    lab = label.strip().lower()
    if not lab:
        return False
    if a == lab or a.startswith(lab):
        return True
    return re.search(r"\b" + re.escape(lab) + r"\b", a) is not None


# ----- parser -----

def _tokenize(text: str) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        out.append((indent, raw.strip()))
    return out


def _action_from_text(action_text: str, lines: list[tuple[int, str]], i: int,
                      branch_indent: int):
    """Build a branch action, consuming nested branch lines for a nested VERIFY."""
    if action_text.startswith("VERIFY:"):
        q = action_text[len("VERIFY:"):].strip()
        sub, i = _parse_branches(lines, i, branch_indent)
        return Verify(q, sub), i
    if action_text == "FINISH" or action_text.startswith("FINISH:"):
        _, _, exp = action_text.partition(":")
        return Finish(exp.strip()), i
    return Prompt(action_text), i


def _parse_branches(lines: list[tuple[int, str]], i: int, parent_indent: int):
    branches: list[Branch] = []
    while i < len(lines):
        indent, content = lines[i]
        if indent <= parent_indent:
            break
        label, sep, action_text = content.partition(":")
        label, action_text = label.strip(), action_text.strip()
        i += 1
        action, i = _action_from_text(action_text, lines, i, indent)
        branches.append(Branch(label, action))
    return branches, i


def parse_program(text: str) -> Program:
    lines = _tokenize(text)
    prog = Program()
    i = 0
    while i < len(lines):
        indent, content = lines[i]
        if content.startswith("PURPOSE:"):
            prog.purpose = content[len("PURPOSE:"):].strip()
            i += 1
        elif content.startswith("INPUT:"):
            prog.input_suffix = content[len("INPUT:"):].strip()
            i += 1
        elif content.startswith("VERIFY:"):
            q = content[len("VERIFY:"):].strip()
            i += 1
            branches, i = _parse_branches(lines, i, indent)
            prog.steps.append(Verify(q, branches))
        elif content == "FINISH" or content.startswith("FINISH:"):
            _, _, exp = content.partition(":")
            prog.steps.append(Finish(exp.strip()))
            i += 1
        else:
            prog.guidance.append(content)
            i += 1
    return prog


# ----- executor -----

@dataclass
class StepLog:
    kind: str
    question: str = ""
    answer: str = ""
    branch: str = ""


@dataclass
class Outcome:
    finished: bool
    expected: str = ""
    log: list[StepLog] = field(default_factory=list)


def run_program(program: Program, ask, *, max_loops: int = 8) -> Outcome:
    """Execute a program's VERIFY/FINISH steps against an ``ask(prompt)->str``
    callable. Returns whether the program reached a satisfied/FINISH state."""
    out = Outcome(finished=False)
    for step in program.steps:
        if isinstance(step, Finish):
            out.finished = True
            out.expected = step.expected
            out.log.append(StepLog("finish", branch=step.expected))
            return out
        if isinstance(step, Verify):
            ok = _run_verify(step, ask, max_loops, out)
            if not ok:
                out.finished = False
                return out
    # All verifies satisfied and no explicit terminal FINISH step: success.
    out.finished = True
    return out


def _run_verify(verify: Verify, ask, max_loops: int, out: Outcome) -> bool:
    loops = 0
    while loops < max_loops:
        loops += 1
        answer = ask(verify.question) or ""
        branch = verify.branch_for(answer)
        out.log.append(StepLog("verify", verify.question, answer,
                               branch.label if branch else WILDCARD))
        if branch is None:
            wc = verify.wildcard()
            if wc and isinstance(wc.action, Prompt):
                ask(wc.action.text)  # re-prompt, then loop back
            continue
        action = branch.action
        if isinstance(action, Finish):
            return True
        if isinstance(action, Verify):
            _run_verify(action, ask, max_loops, out)  # recursive diagnosis
            continue                                   # then re-evaluate this verify
        if isinstance(action, Prompt):
            ask(action.text)                           # feedback, then loop back
            continue
    return False  # exceeded the loop budget without satisfying the verify
