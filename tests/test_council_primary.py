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
