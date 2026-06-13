"""Reconciliation request_* tools spawn and run the right child roles."""
from swarm import ids
from tests.conftest import MockClient, make_runtime


def test_request_testing_spawns_tester(project):
    ids._counters.clear()

    def script(last_user, model, n):
        if "child agents finished" in last_user:
            return '<<tool:finish>>{"status":"complete","summary":"reviewed test results"}<</tool>>'
        if "ROLE: code" in last_user:
            return '<<tool:request_testing>>{"target":"reverse.py","context":"verify it reverses"}<</tool>>'
        # the tester child
        return '<<tool:finish>>{"status":"complete","summary":"tests pass","note":"3 passed"}<</tool>>'

    ctx, runner = make_runtime(project, MockClient(script))
    sid = ids.next_id("swarm")
    ctx.db.create_swarm(sid, "build + test")
    root = ctx.create_root(sid, "code", "Root", "write and test reverse")
    result = runner.run_agent(root["id"])

    assert result["status"] == "complete"
    agents = ctx.db.list_swarm_agents(sid)
    roles = {a["role"] for a in agents}
    assert "tester" in roles
    tester = [a for a in agents if a["role"] == "tester"][0]
    assert tester["parent_agent_id"] == root["id"]
    assert tester["status"] == "complete"


def test_request_fix_chain(project):
    ids._counters.clear()

    def script(last_user, model, n):
        if "Fix this specific failure" in last_user and "ROLE: fixer" in last_user:
            return '<<tool:finish>>{"status":"complete","summary":"fixed off-by-one"}<</tool>>'
        if "child agents finished" in last_user:
            return '<<tool:finish>>{"status":"complete","summary":"done after fix"}<</tool>>'
        if "ROLE: tester" in last_user:
            return '<<tool:request_fix>>{"target":"assertion error in test_x","context":".."}<</tool>>'
        return '<<tool:finish>>{"status":"complete"}<</tool>>'

    ctx, runner = make_runtime(project, MockClient(script))
    sid = ids.next_id("swarm")
    ctx.db.create_swarm(sid, "test then fix")
    root = ctx.create_root(sid, "tester", "Root", "test the module")
    runner.run_agent(root["id"])

    roles = {a["role"] for a in ctx.db.list_swarm_agents(sid)}
    assert "fixer" in roles
