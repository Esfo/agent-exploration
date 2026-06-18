"""Verify recursive agents inherit the full branch conversation + unique purpose."""
from swarm import ids
from tests.conftest import MockClient, make_runtime


def test_child_inherits_conversation_and_has_unique_purpose(project):
    ids._counters.clear()

    def script(last_user, model, n):
        if "child agents finished" in last_user:
            return '<<tool:finish>>{"status":"complete","summary":"merged"}<</tool>>'
        if "ROLE: progenitor" in last_user:
            return ('<<tool:spawn_agents>>{"children":[{"title":"sub","task":"do the sub-piece",'
                    '"role":"coding_agent"}]}<</tool>>')
        return '<<tool:finish>>{"status":"complete","summary":"leaf"}<</tool>>'

    client = MockClient(script)
    ctx, runner = make_runtime(project, client)
    sid = ids.next_id("swarm")
    ctx.db.create_swarm(sid, "build the whole thing")
    root = ctx.create_root(sid, "progenitor", "Root", "build the whole thing")
    runner.run_agent(root["id"])

    # Find the child's model call: the one whose prompt contains the child's task.
    def joined(call):
        return "\n".join(m["content"] for m in call["messages"])

    child_calls = [c for c in client.calls if "do the sub-piece" in joined(c)
                   and "ROLE: coding_agent" in joined(c)]
    assert child_calls, "no child call found"
    text = joined(child_calls[0])

    # Inherited the parent's conversation (root purpose carries the root task)...
    assert "build the whole thing" in text
    assert "ROLE: progenitor" in text          # the parent's purpose is present
    # ...and carries its own unique purpose.
    assert "This is your purpose: ROLE: coding_agent" in text
    assert "return your result to your parent branch" in text


def test_root_has_no_inherited_history(project):
    ids._counters.clear()
    client = MockClient(lambda *_: '<<tool:finish>>{"status":"complete"}<</tool>>')
    ctx, runner = make_runtime(project, client)
    sid = ids.next_id("swarm")
    ctx.db.create_swarm(sid, "solo goal")
    root = ctx.create_root(sid, "progenitor", "Root", "solo goal")
    runner.run_agent(root["id"])

    first = client.calls[0]["messages"]
    # system + purpose only (no inherited conversation for the root).
    assert first[0]["role"] == "system"
    users = [m for m in first if m["role"] == "user"]
    assert len(users) == 1
    assert users[0]["content"].startswith("This is your purpose")
    assert "solo goal" in users[0]["content"]
