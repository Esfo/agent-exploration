from conftest import MockClient, make_runtime

from swarm.council import parse_directives
from swarm.primary import PrimaryAgent, _ends_yes


def test_parse_directives(project):
    rt = make_runtime(project, client=None)
    text = (
        "coding: write parser: Implement the tolerant arrow parser.\n\n"
        "philosophizing: check intent: Make sure it matches the human goal.\n\n"
        "nonexistent: bogus: should be skipped\n"
    )
    members = parse_directives(rt, text)
    assert [m.agent_type for m in members] == ["coding", "philosophizing"]
    assert members[0].task_truncated == "write parser"
    assert members[0].task == "Implement the tolerant arrow parser."


def test_parse_directives_tolerates_markdown_and_case(project):
    rt = make_runtime(project, client=None)
    text = (
        "- **Coding**: Write parser: Implement the parser.\n"
        "1. Math : Check complexity: Validate it.\n"
        "* philosophizing: Judge intent: Make sure.\n"
        "some prose that should be ignored\n"
    )
    members = parse_directives(rt, text)
    assert [m.agent_type for m in members] == ["coding", "math", "philosophizing"]
    assert members[0].task_truncated == "Write parser"


def test_collect_directives_confirmation_loop(project):
    from swarm.council import collect_directives
    rt = make_runtime(project, client=None)
    replies = iter([
        "coding: build it: Do the work.",   # initial directives
        "no, that's wrong",                 # confirmation -> NO -> resubmit
        "coding: build it: Do the work.",   # resubmitted directives
        "yes that's right",                 # confirmation -> YES -> spawn
    ])
    asked = []

    def ask(text):
        asked.append(text)
        return next(replies)

    members = collect_directives(rt, "These are the agent types:", ask, lambda s: None)
    assert [m.agent_type for m in members] == ["coding"]
    # The collected directive was echoed back for confirmation.
    assert any("Is this correct?" in t and "coding: build it: Do the work." in t
               for t in asked)


def test_ends_yes():
    assert _ends_yes("after weighing it, YES") is True
    assert _ends_yes("not yet, NO") is False
    assert _ends_yes("I lean YES but ultimately NO") is False


def make_script(state):
    """A model that plans, answers the hidden confirm check, then drives the
    council + zipper. ``state['ready']`` flips the confirm verdict."""
    def script(last_user, system, n):
        # hidden confirm query
        if "has the user actually agreed" in last_user or "decide one thing only" in last_user:
            return "Reasoning privately...\n" + ("YES" if state["ready"] else "NO")
        # goal-extraction query
        if "state the single goal" in last_user:
            return "Build the whole thing."
        # directive confirmation step
        if "Is this correct?" in last_user:
            return "Looks right. YES"
        # SPAWNING query
        if "These are the agent types" in last_user:
            return "coding: build it: Write the whole thing."
        # convergence
        if "Would you like to run any of your tools" in last_user:
            return "EXIT"
        if "vote either FINISHED or INCOMPLETE" in last_user:
            return "Complete.\nI vote FINISHED"
        if "Form either a plan or a prototype" in last_user:
            return "FINISHED OUTPUT\nthe built thing"
        # zipper
        if "finalizing the work of a council" in last_user:
            return "RETAIN coding"
        if "Is this the final response" in last_user:
            return "CONFIRM"
        # a visible planning turn: agreement words set readiness for next confirm
        state["ready"] = last_user.strip().lower().startswith(("yes", "go ahead", "do it"))
        return "Here's the plan. Shall I begin?"
    return script


def test_primary_plans_then_confirms_then_spawns(project):
    state = {"ready": False}
    rt = make_runtime(project, MockClient(make_script(state)))
    primary = PrimaryAgent(rt)

    # First turn: still planning, hidden confirm says NO -> just a reply.
    reply = primary.send("I want a tool that does X")
    assert "Shall I begin?" in reply
    assert "FINISHED OUTPUT" not in reply

    # User agrees -> hidden confirm says YES -> swarm runs, result appended.
    final = primary.send("yes, go ahead")
    assert "FINISHED OUTPUT" in final
    assert "the built thing" in final


def test_run_once_spawns_immediately(project):
    # --oneprompt path: no planning, no confirm dialogue; spawns right away.
    state = {"ready": False}
    rt = make_runtime(project, MockClient(make_script(state)))
    primary = PrimaryAgent(rt)
    final = primary.run_once("build me a CSV summariser")
    assert "FINISHED OUTPUT" in final
    # The goal is summarized via the goal query (not the raw prompt).
    assert primary.goal == "Build the whole thing."
    # The confirm check was never consulted (state stayed False).
    assert state["ready"] is False
