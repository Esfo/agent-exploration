"""Code work-unit pipeline: code -> testing_agent -> philosopher, sequential."""
from swarm import ids
from tests.conftest import MockClient, make_runtime


def _enable(project):
    sp = project / "settings" / "main.settings"
    sp.write_text(sp.read_text().replace("CODE_PIPELINE_ENABLED=false", "CODE_PIPELINE_ENABLED=true"))


def test_code_child_runs_three_stage_pipeline(project):
    _enable(project)
    ids._counters.clear()
    order = []

    def script(last_user, model, n):
        if "ROLE: progenitor" in last_user:
            return ('<<tool:spawn_agents>>{"children":[{"title":"impl","task":"implement add()",'
                    '"role":"coding_agent"}]}<</tool>>')
        if "child agents finished" in last_user:
            return '<<tool:finish>>{"status":"complete","summary":"done"}<</tool>>'
        if "ROLE: testing_agent" in last_user:
            order.append("testing_agent")
            return '<<tool:finish>>{"status":"complete","summary":"code matches spec PASS"}<</tool>>'
        if "ROLE: philosopher" in last_user:
            order.append("philosopher")
            return '<<tool:finish>>{"status":"complete","summary":"meets human intent"}<</tool>>'
        # the coding model
        order.append("coding_agent")
        return '<<tool:finish>>{"status":"complete","summary":"wrote add()"}<</tool>>'

    ctx, runner = make_runtime(project, MockClient(script))
    sid = ids.next_id("swarm")
    ctx.db.create_swarm(sid, "build add()")
    root = ctx.create_root(sid, "progenitor", "Root", "build add()")
    runner.run_agent(root["id"])

    roles = {a["role"] for a in ctx.db.list_swarm_agents(sid)}
    assert {"coding_agent", "testing_agent", "philosopher"} <= roles
    # ran one at a time, in order, code first then checker then philosopher
    assert order == ["coding_agent", "testing_agent", "philosopher"]

    # checker + philosopher are children of the code agent (the work unit)
    code_agent = [a for a in ctx.db.list_swarm_agents(sid) if a["role"] == "coding_agent"][0]
    checker = [a for a in ctx.db.list_swarm_agents(sid) if a["role"] == "testing_agent"][0]
    phil = [a for a in ctx.db.list_swarm_agents(sid) if a["role"] == "philosopher"][0]
    assert checker["parent_agent_id"] == code_agent["id"]
    assert phil["parent_agent_id"] == code_agent["id"]


def test_checker_sees_code_in_inherited_conversation(project):
    _enable(project)
    ids._counters.clear()
    client_seen = {}

    def script(last_user, model, n):
        if "ROLE: progenitor" in last_user:
            return ('<<tool:spawn_agents>>{"children":[{"title":"impl","task":"implement add()",'
                    '"role":"coding_agent"}]}<</tool>>')
        if "child agents finished" in last_user:
            return '<<tool:finish>>{"status":"complete"}<</tool>>'
        if ("ROLE: coding_agent" in last_user and "ROLE: testing_agent" not in last_user
                and "ROLE: philosopher" not in last_user):
            if "Tool write_file result" in last_user:  # already wrote -> finish
                return '<<tool:finish>>{"status":"complete","summary":"wrote add"}<</tool>>'
            return '<<tool:write_file>>{"path":"add.py","content":"def add(a,b):\\n    return a+b\\n"}<</tool>>'
        return '<<tool:finish>>{"status":"complete","summary":"ok"}<</tool>>'

    client = MockClient(script)
    ctx, runner = make_runtime(project, client)
    sid = ids.next_id("swarm")
    ctx.db.create_swarm(sid, "build add()")
    root = ctx.create_root(sid, "progenitor", "Root", "build add()")
    runner.run_agent(root["id"])

    # find a checker call and confirm the code (write_file with def add) is in its prompt
    checker_calls = [c for c in client.calls
                     if any("ROLE: testing_agent" in m["content"] for m in c["messages"])]
    assert checker_calls
    blob = "\n".join(m["content"] for m in checker_calls[0]["messages"])
    assert "def add" in blob  # the checker inherited the code agent's output
