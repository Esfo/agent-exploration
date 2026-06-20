"""Audit the conversational properties: history accumulation, inheritance, the
queries-are-ephemeral / results-are-inserted rule, and the hidden confirm check."""
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


def make_primary_script(state):
    def script(last_user, system, n):
        if "has the user actually agreed" in last_user:        # hidden confirm
            return "YES" if state["ready"] else "NO"
        if "These are the agent types" in last_user:           # SPAWNING query
            return "coding: build it: Build the whole thing."
        out = _council_script(last_user, system, n)
        if out != "ok":
            return out
        # visible planning turn
        state["ready"] = last_user.strip().lower().startswith(("yes", "go ahead"))
        if last_user.startswith("now also"):
            return "Sure — building on what we just produced."
        return "Here's the plan. Shall I begin?"
    return script


def test_council_member_history_accumulates(project):
    rt = make_runtime(project, MockClient(_council_script))
    m = Member(ids.next_id("agent"), "coding", "build it", "build it")
    seed = [{"role": "user", "content": "inherited planning context"}]
    run_convergence(rt, [m], seed, "ship it", "c1", max_rounds=2)
    assert m.messages[0]["content"] == "inherited planning context"
    assert any(r["role"] == "assistant" for r in m.messages)
    assert any("vote" in r["content"].lower() for r in m.messages if r["role"] == "user")


def test_confirm_is_ephemeral_and_invisible(project):
    state = {"ready": False}
    rt = make_runtime(project, MockClient(make_primary_script(state)))
    p = PrimaryAgent(rt)
    reply = p.send("I want a tool")
    # The hidden confirm dialogue must never appear in the reply...
    assert "YES" not in reply and "NO" not in reply
    # ...nor be persisted in the primary's history.
    assert not any("has the user actually agreed" in m["content"] for m in p.messages)


def test_spawning_query_ephemeral_and_result_inserted(project):
    state = {"ready": False}
    rt = make_runtime(project, MockClient(make_primary_script(state)))
    p = PrimaryAgent(rt)
    p.send("I want a tool")
    result = p.send("yes")

    # SPAWNING query is not persisted...
    assert not any("These are the agent types" in m["content"] for m in p.messages)
    # ...but the council result IS inserted as the primary's own turn.
    assert p.messages[-1]["role"] == "assistant"
    assert "the built thing" in p.messages[-1]["content"]
    assert "the built thing" in result


def test_conversation_continues_after_swarm(project):
    state = {"ready": False}
    rt = make_runtime(project, MockClient(make_primary_script(state)))
    p = PrimaryAgent(rt)
    p.send("I want a tool")
    p.send("yes")                       # spawns
    n_before = len(p.messages)
    follow = p.send("now also handle TSV")   # confirm NO -> normal turn
    assert "building on what we just produced" in follow
    # one visible user + one visible assistant turn added (confirm is ephemeral)
    assert len(p.messages) == n_before + 2
