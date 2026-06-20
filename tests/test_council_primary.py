from conftest import MockClient, make_runtime

from swarm.council import parse_directives
from swarm.primary import PrimaryAgent, parse_yes


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


def test_parse_yes():
    assert parse_yes("yes please") is True
    assert parse_yes("no not yet") is False
    assert parse_yes("maybe possibly") is None


def _full_script(last_user, system, n):
    # SPAWNING query (checked first: its file also opens with "I want ...")
    if "These are the agent types" in last_user:
        return "coding: build it: Write the whole thing."
    # primary planning turn
    if last_user.startswith("I want a tool"):
        return "Here's my plan to build it. <<READY>>"
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
    return "ok"


def test_primary_plan_then_spawn(project):
    rt = make_runtime(project, MockClient(_full_script))
    primary = PrimaryAgent(rt)

    reply = primary.send("I want a tool that does X")
    assert "Would you like me to spawn agents" in reply
    assert primary.state == PrimaryAgent.AWAITING_CONFIRM
    assert "<<READY>>" not in reply

    final = primary.send("yes")
    assert final.startswith("FINISHED OUTPUT")
    assert "the built thing" in final
    assert primary.state == PrimaryAgent.CHATTING
