"""Escalation: convergence never ends INCOMPLETE — it adds peers (form a) or lets
a dissenting agent take its job over as its own sub-swarm (form b)."""
from pathlib import Path

from swarm import ids
from swarm.agent_loop import required_peer_roles
from tests.conftest import MockClient, make_runtime


def test_required_peer_roles():
    # a coding agent requires testing + philosophy peers
    assert required_peer_roles(["coding_agent"]) == ["testing_agent", "philosopher"]
    # already complete -> nothing missing
    assert required_peer_roles(["coding_agent", "testing_agent", "philosopher"]) == []
    # only the missing ones are added
    assert required_peer_roles(["coding_agent", "testing_agent"]) == ["philosopher"]
    # no work roles -> no required peers
    assert required_peer_roles(["researcher"]) == []


def test_add_required_peers_creates_missing(project):
    ids._counters.clear()
    ctx, runner = make_runtime(project, MockClient(lambda *a: "ok"))
    sid = ids.next_id("swarm")
    ctx.db.create_swarm(sid, "g")
    root = ctx.create_root(sid, "chat_agent", "Root", "build")
    coder = ctx.create_child(parent=root, title="impl", task="t", role="coding_agent",
                             done_condition="", suggested_model=None, priority=1)

    peers = runner._add_required_peers([dict(coder)], "code")
    roles = sorted(p["role"] for p in peers)
    assert roles == ["philosopher", "testing_agent"]


def test_maybe_subswarm_spawns_into_agent_dir(project):
    ids._counters.clear()

    def script(last_user, model, n):
        if "its own swarm" in last_user:        # the wants-subswarm question
            return "YES"
        return '<<tool:finish>>{"status":"complete","summary":"did the sub-task"}<</tool>>'

    ctx, runner = make_runtime(project, MockClient(script))
    sid = ids.next_id("swarm")
    ctx.db.create_swarm(sid, "g")
    root = ctx.create_root(sid, "chat_agent", "Root", "build")
    coder = ctx.create_child(parent=root, title="big job", task="do a big thing",
                             role="coding_agent", done_condition="",
                             suggested_model=None, priority=1)

    did = runner._maybe_subswarm(dict(coder), conversation=[], goal_type="code")
    assert did is True
    # the sub-swarm's children were created under the dissenting agent
    children = ctx.db.list_children(coder["id"])
    child_roles = sorted(c["role"] for c in children)
    # its own role plus the required peers
    assert "coding_agent" in child_roles
    assert "testing_agent" in child_roles and "philosopher" in child_roles


def test_maybe_subswarm_declines_on_no(project):
    ids._counters.clear()

    def script(last_user, model, n):
        if "its own swarm" in last_user:
            return "NO"
        return '<<tool:finish>>{"status":"complete"}<</tool>>'

    ctx, runner = make_runtime(project, MockClient(script))
    sid = ids.next_id("swarm")
    ctx.db.create_swarm(sid, "g")
    root = ctx.create_root(sid, "chat_agent", "Root", "build")
    coder = ctx.create_child(parent=root, title="job", task="t", role="coding_agent",
                             done_condition="", suggested_model=None, priority=1)

    assert runner._maybe_subswarm(dict(coder), conversation=[], goal_type="code") is False
    assert ctx.db.list_children(coder["id"]) == []
