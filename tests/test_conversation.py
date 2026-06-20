"""Audit the conversational properties: history accumulation, inheritance, and
the queries-are-ephemeral / results-are-inserted rule."""
from conftest import MockClient, make_runtime

from swarm import ids
from swarm.convergence import Member, run_convergence
from swarm.primary import PrimaryAgent


def _council_script(last_user, system, n):
    if "Would you like to run any of your tools" in last_user:
        return "EXIT"
    if "vote either FINISHED or INCOMPLETE" in last_user:
        return "Looks complete.\nI vote FINISHED"
    if "Form either a plan or a prototype" in last_user:
        return "FINISHED OUTPUT\nthe built thing"
    if "finalizing the work of a council" in last_user:
        return "RETAIN coding"
    if "Is this the final response" in last_user:
        return "CONFIRM"
    return "ok"


def _primary_script(last_user, system, n):
    if "These are the agent types" in last_user:          # SPAWNING query
        return "coding: build it: Build the whole thing."
    if last_user.startswith("I want"):
        return "Here's the plan. <<READY>>"
    if last_user.startswith("now also"):                   # follow-up after swarm
        return "Sure — building on what we just produced."
    return _council_script(last_user, system, n)


def test_council_member_history_accumulates(project):
    rt = make_runtime(project, MockClient(_council_script))
    m = Member(ids.next_id("agent"), "coding", "build it", "build it")
    seed = [{"role": "user", "content": "inherited planning context"}]
    run_convergence(rt, [m], seed, "ship it", "c1", max_rounds=2)
    # Inherited context is at the front; the member's own turns accumulate after.
    assert m.messages[0]["content"] == "inherited planning context"
    assert any(r["role"] == "assistant" for r in m.messages)
    # The convene/vote turns are part of the member's ongoing conversation.
    assert any("vote" in r["content"].lower() for r in m.messages if r["role"] == "user")


def test_spawning_query_is_ephemeral_and_result_inserted(project):
    rt = make_runtime(project, MockClient(_primary_script))
    p = PrimaryAgent(rt)
    p.send("I want a tool")
    result = p.send("yes")

    # The SPAWNING query text must NOT be persisted in the primary's history...
    assert not any("These are the agent types" in msg["content"] for msg in p.messages)
    # ...but the council's result IS inserted as the primary's own turn.
    assert p.messages[-1]["role"] == "assistant"
    assert p.messages[-1]["content"] == result
    assert "the built thing" in result


def test_conversation_continues_after_swarm(project):
    rt = make_runtime(project, MockClient(_primary_script))
    p = PrimaryAgent(rt)
    p.send("I want a tool")
    p.send("yes")
    n_before = len(p.messages)
    follow = p.send("now also handle TSV")
    # A follow-up is a normal conversational turn with the swarm result in context.
    assert "building on what we just produced" in follow
    assert len(p.messages) == n_before + 2  # user + assistant
