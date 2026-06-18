"""The PURPOSE/INPUT/VERIFY/FINISH instruction-program grammar."""
from swarm.instruction_program import (Finish, Prompt, Verify, parse_program,
                                       run_program)

EXAMPLE = """\
PURPOSE: You are a verification agent. You design and run tests.
INPUT:
VERIFY: Is your test comprehensive and complete?
    YES: FINISH
    NO: VERIFY: Does this task need to be broken into smaller pieces?
        YES: Split it into sub-tasks and try again.
        NO: Improve the test, then re-check.
        ?: Please answer YES or NO.
    ?: I didn't catch your answer, please answer in the expected format.
FINISH: I vote FINISHED
"""


def test_parse_structure():
    p = parse_program(EXAMPLE)
    assert p.purpose.startswith("You are a verification agent")
    assert p.input_suffix == ""
    # two top-level steps: the VERIFY and the terminal FINISH
    assert isinstance(p.steps[0], Verify)
    assert isinstance(p.steps[1], Finish)
    assert p.steps[1].expected == "I vote FINISHED"

    v = p.steps[0]
    labels = [b.label for b in v.branches]
    assert labels == ["YES", "NO", "?"]
    assert isinstance(v.branches[0].action, Finish)
    # NO -> nested VERIFY with its own YES/NO/? branches
    nested = v.branches[1].action
    assert isinstance(nested, Verify)
    assert [b.label for b in nested.branches] == ["YES", "NO", "?"]
    assert isinstance(v.branches[2].action, Prompt)


def test_run_yes_finishes_immediately():
    p = parse_program(EXAMPLE)
    asked = []

    def ask(q):
        asked.append(q)
        return "YES"

    out = run_program(p, ask)
    assert out.finished is True
    assert out.expected == "I vote FINISHED"
    # only the top verify was asked before YES -> FINISH, then terminal FINISH
    assert asked == ["Is your test comprehensive and complete?"]


def test_wildcard_loops_until_valid_answer():
    p = parse_program(EXAMPLE)
    answers = iter(["garbled", "YES"])
    asked = []

    def ask(q):
        asked.append(q)
        # the wildcard re-prompt is also routed through ask(); answer only to the
        # top verify question, return "" to the wildcard prompt.
        if q.startswith("Is your test"):
            return next(answers)
        return ""

    out = run_program(p, ask)
    assert out.finished is True
    # asked the top question twice (garbled -> wildcard -> retry -> YES)
    top = [q for q in asked if q.startswith("Is your test")]
    assert len(top) == 2


def test_nested_verify_then_reevaluate():
    p = parse_program(EXAMPLE)
    # First top answer NO -> descend into nested verify (answer NO -> feedback),
    # then re-evaluate top -> YES -> finish.
    top_answers = iter(["NO", "YES"])

    def ask(q):
        if q.startswith("Is your test"):
            return next(top_answers)
        if q.startswith("Does this task"):
            return "NO"
        return ""

    out = run_program(p, ask)
    assert out.finished is True


def test_unsatisfied_verify_returns_incomplete():
    p = parse_program(EXAMPLE)

    def ask(q):
        return "NO" if q.startswith("Is your test") else "NO"

    out = run_program(p, ask, max_loops=3)
    assert out.finished is False


def test_input_suffix_parsed():
    p = parse_program("PURPOSE: x\nINPUT: extra context appended here\nVERIFY: ok?\n    YES: FINISH\n    ?: retry\n")
    assert p.input_suffix == "extra context appended here"


def test_render_input_substitutes_actual_and_appends_suffix():
    p = parse_program("PURPOSE: x\nINPUT: please be thorough\nVERIFY: ok?\n    YES: FINISH\n    ?: retry\n")
    # actual input is hard-substituted, suffix appended after it
    rendered = p.render_input("the upstream handoff")
    assert rendered == "the upstream handoff\n\nplease be thorough"
    # with no actual input, only the suffix remains
    assert p.render_input("") == "please be thorough"
    # with no suffix, only the actual input
    p2 = parse_program("PURPOSE: x\nINPUT:\nVERIFY: ok?\n    YES: FINISH\n    ?: r\n")
    assert p2.render_input("just the input") == "just the input"


def test_system_text_has_purpose_and_guidance():
    from swarm.instruction_program import parse_program as pp
    p = pp("PURPOSE: do the thing\nINPUT:\n001. step one\n002. step two\nVERIFY: ok?\n    YES: FINISH\n    ?: r\n")
    s = p.system_text()
    assert s.startswith("PURPOSE: do the thing")
    assert "001. step one" in s and "002. step two" in s


def test_messages_to_text_flattens():
    from swarm.instruction_program import messages_to_text
    txt = messages_to_text([{"role": "user", "content": "hi"},
                            {"role": "assistant", "content": "yo"},
                            {"role": "user", "content": "  "}])
    assert txt == "[user] hi\n\n[assistant] yo"
