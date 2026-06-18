"""End-to-end agent loop tests using a scripted mock model (no live Ollama)."""
from swarm import ids
from tests.conftest import MockClient, make_runtime


def test_model_selector_falls_back_to_default(project):
    ctx, _ = make_runtime(project, MockClient(lambda *_: ""))
    cfg = ctx.selector.resolve("coding_agent")
    assert cfg.selected_model == "mock-model:latest"
    assert cfg.model_source == "default_fallback"
    # num_ctx auto + probe unavailable -> conservative fallback, capped by MAX_AUTO_NUM_CTX.
    assert cfg.num_ctx <= 16384


def test_single_agent_finishes(project):
    ids._counters.clear()

    def script(last_user, model, n):
        return '<<tool:finish>>{"status":"complete","summary":"all done","note":"ok"}<</tool>>'

    ctx, runner = make_runtime(project, MockClient(script))
    sid = ids.next_id("swarm")
    ctx.db.create_swarm(sid, "do a thing")
    root = ctx.create_root(sid, "chat_agent", "Root", "do a thing")
    result = runner.run_agent(root["id"])
    assert result["status"] == "complete"
    assert ctx.db.get_agent(root["id"])["status"] == "complete"


def test_spawn_then_finish(project):
    ids._counters.clear()

    def script(last_user, model, n):
        # Root spawns one child the first time; children report their results
        # back via the "child agents finished" message; everyone then finishes.
        if "child agents finished" in last_user:
            return '<<tool:finish>>{"status":"complete","summary":"integrated children","note":"done"}<</tool>>'
        if "ROLE: chat_agent" in last_user:
            return ('<<tool:spawn_agents>>{"children":[{"title":"sub","task":"do sub",'
                    '"role":"coding_agent","done_condition":"sub done"}]}<</tool>>')
        return '<<tool:finish>>{"status":"complete","summary":"leaf done","note":"leaf"}<</tool>>'

    ctx, runner = make_runtime(project, MockClient(script))
    sid = ids.next_id("swarm")
    ctx.db.create_swarm(sid, "build thing")
    root = ctx.create_root(sid, "chat_agent", "Root", "build thing")
    result = runner.run_agent(root["id"])

    assert result["status"] == "complete"
    agents = ctx.db.list_swarm_agents(sid)
    assert len(agents) == 2  # root + 1 child
    child = [a for a in agents if a["parent_agent_id"] == root["id"]][0]
    assert child["status"] == "complete"
    assert child["role"] == "coding_agent"


def test_recursion_depth_ceiling(project):
    ids._counters.clear()
    # Force a low ceiling by editing settings in place.
    sp = project / "settings" / "main.settings"
    sp.write_text(sp.read_text().replace("MAX_RECURSION_DEPTH=unlimited", "MAX_RECURSION_DEPTH=1"))

    def script(last_user, model, n):
        if "child agents finished" in last_user or "blocked" in last_user.lower():
            return '<<tool:finish>>{"status":"complete","summary":"wrapped up"}<</tool>>'
        # Every agent tries to spawn; ceiling must stop runaway recursion.
        return ('<<tool:spawn_agents>>{"children":[{"title":"deeper","task":"go deeper",'
                '"role":"coding_agent"}]}<</tool>>')

    ctx, runner = make_runtime(project, MockClient(script))
    sid = ids.next_id("swarm")
    ctx.db.create_swarm(sid, "deep")
    root = ctx.create_root(sid, "chat_agent", "Root", "deep")
    runner.run_agent(root["id"])

    agents = ctx.db.list_swarm_agents(sid)
    # depth 0 root + depth 1 children only; no depth >= 2 may exist.
    assert max(a["depth"] for a in agents) <= 1


def test_non_tool_output_then_finish(project):
    ids._counters.clear()
    state = {"n": 0}

    def script(last_user, model, n):
        state["n"] += 1
        if state["n"] == 1:
            return "I am thinking about the problem but emitting no tool."
        return '<<tool:finish>>{"status":"complete","summary":"recovered"}<</tool>>'

    ctx, runner = make_runtime(project, MockClient(script))
    sid = ids.next_id("swarm")
    ctx.db.create_swarm(sid, "x")
    root = ctx.create_root(sid, "chat_agent", "Root", "x")
    result = runner.run_agent(root["id"])
    assert result["status"] == "complete"
