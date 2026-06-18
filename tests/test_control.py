"""Live control: cancel, stop-after-wave, and docker preflight."""
from swarm import ids
from swarm.control import RunControl
from swarm.settings import Settings
from tests.conftest import MockClient, make_runtime


def _settings(project):
    return Settings.load(project / "settings" / "main.settings")


def test_cancel_stops_agent_before_work(project):
    ids._counters.clear()

    def script(last_user, model, n):
        return '<<tool:finish>>{"status":"complete"}<</tool>>'

    ctx, runner = make_runtime(project, MockClient(script))
    ctx.control = RunControl()
    ctx.control.cancel()  # cancel the whole swarm up front
    sid = ids.next_id("swarm")
    ctx.db.create_swarm(sid, "g")
    root = ctx.create_root(sid, "coding_agent", "Root", "do work")
    result = runner.run_agent(root["id"])
    assert result["status"] == "cancelled"
    assert ctx.db.get_agent(root["id"])["status"] == "cancelled"


def test_stop_after_wave_prevents_new_children(project):
    ids._counters.clear()

    def script(last_user, model, n):
        if "Stop requested" in last_user:
            return '<<tool:finish>>{"status":"complete","summary":"stopped cleanly"}<</tool>>'
        if "ROLE: chat_agent" in last_user:
            return ('<<tool:spawn_agents>>{"children":[{"title":"x","task":"t","role":"coding_agent"}]}<</tool>>')
        return '<<tool:finish>>{"status":"complete"}<</tool>>'

    ctx, runner = make_runtime(project, MockClient(script))
    ctx.control = RunControl()
    ctx.control.stop_after_wave()
    sid = ids.next_id("swarm")
    ctx.db.create_swarm(sid, "g")
    root = ctx.create_root(sid, "chat_agent", "Root", "build")
    result = runner.run_agent(root["id"])

    assert result["status"] == "complete"
    # The child was created by the spawn tool but never run (no new wave).
    children = [a for a in ctx.db.list_swarm_agents(sid) if a["parent_agent_id"] == root["id"]]
    assert all(c["status"] in ("created", "queued") for c in children)


def test_runcontrol_state():
    c = RunControl()
    assert not c.paused
    c.pause(); assert c.paused
    c.resume(); assert not c.paused
    c.cancel("agent_0009"); assert c.is_cancelled("agent_0009")
    assert not c.is_cancelled("agent_0010")
    c.cancel(); assert c.is_cancelled("agent_0010")  # cancel-all
    c.stop_after_wave(); assert c.should_stop_waves()
    c.reset()
    assert not c.is_cancelled("agent_0010") and not c.should_stop_waves()


def test_docker_preflight_no_daemon(project, monkeypatch):
    import swarm.sandbox as sb
    monkeypatch.setattr(sb, "docker_available", lambda: False)
    s = _settings(project)  # SANDBOX_BACKEND=docker in project settings
    assert sb.docker_preflight(s) == "daemon_unavailable"


def test_docker_preflight_skips_for_subprocess(project, monkeypatch):
    import swarm.sandbox as sb
    s = _settings(project)
    s._v["SANDBOX_BACKEND"] = "subprocess"
    assert sb.docker_preflight(s) == "skipped (backend != docker)"
