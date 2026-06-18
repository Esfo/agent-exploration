"""Spawn-inherit overflow: a summarizer agent compresses the first 60%."""
from swarm import ids
from tests.conftest import MockClient, make_runtime


def _cap(project, n):
    sp = project / "settings" / "main.settings"
    sp.write_text(sp.read_text().replace("SUMMARIZE_SPAWN_MAX_TOKENS=0",
                                         f"SUMMARIZE_SPAWN_MAX_TOKENS={n}"))


def test_needs_summary_threshold(project):
    ctx, runner = make_runtime(project, MockClient(lambda *_: ""))
    agent = {"num_ctx": 8192, "num_predict": 2048}
    small = [{"role": "user", "content": "hi"}]
    big = [{"role": "user", "content": "x " * 5000}]
    # explicit cap path
    ctx.settings._v["SUMMARIZE_SPAWN_MAX_TOKENS"] = "50"
    assert runner._needs_summary(agent, small) is False
    assert runner._needs_summary(agent, big) is True


def test_summarize_branch_replaces_first_fraction(project):
    ctx, runner = make_runtime(project, MockClient(
        lambda last_user, *_: "BRIEFING: goal=build X; wrote a.py; tests pass."))
    ids._counters.clear()
    sid = ids.next_id("swarm")
    ctx.db.create_swarm(sid, "g")
    parent = ctx.create_root(sid, "chat_agent", "Root", "build X")
    convo = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"msg {i}"}
             for i in range(10)]
    out = runner._summarize_branch(dict(parent), convo)

    # first 60% (6 msgs) replaced by one summary prefix; last 40% (4) kept
    assert out[0]["content"].startswith("[SUMMARY OF EARLIER CONVERSATION]")
    assert "BRIEFING: goal=build X" in out[0]["content"]
    assert out[1:] == convo[6:]
    # a summarizer agent was spawned and recorded
    sumz = [a for a in ctx.db.list_swarm_agents(sid) if a["role"] == "summarizer"]
    assert len(sumz) == 1 and sumz[0]["status"] == "complete"


def test_summarizer_fallback_when_model_unavailable(project):
    # model raises -> deterministic recap still produced
    class Boom(MockClient):
        def chat(self, *a, **k):
            raise RuntimeError("ollama down")
    ctx, runner = make_runtime(project, Boom(lambda *_: ""))
    ids._counters.clear()
    sid = ids.next_id("swarm")
    ctx.db.create_swarm(sid, "g")
    parent = ctx.create_root(sid, "chat_agent", "Root", "build X")
    convo = [{"role": "user", "content": f"detail number {i}"} for i in range(10)]
    out = runner._summarize_branch(dict(parent), convo)
    assert out[0]["content"].startswith("[SUMMARY OF EARLIER CONVERSATION]")
    assert "earlier context summarized" in out[0]["content"]


def test_children_inherit_summary_on_overflow(project):
    _cap(project, 40)  # tiny cap -> any real branch conversation overflows
    ids._counters.clear()

    def script(last_user, model, n):
        # summarizer call: system carries the summarizing checks
        if "compact briefing" in last_user or "Summarize the earlier" in last_user:
            return "BRIEFING: root asked to build; proceeding."
        if "child agents finished" in last_user:
            return '<<tool:finish>>{"status":"complete","summary":"done"}<</tool>>'
        if "ROLE: chat_agent" in last_user:
            return ('<<tool:spawn_agents>>{"children":[{"title":"sub","task":"do sub piece",'
                    '"role":"coding_agent"}]}<</tool>>')
        return '<<tool:finish>>{"status":"complete","summary":"leaf"}<</tool>>'

    client = MockClient(script)
    ctx, runner = make_runtime(project, client)
    sid = ids.next_id("swarm")
    ctx.db.create_swarm(sid, "build the thing")
    root = ctx.create_root(sid, "chat_agent", "Root", "build the thing")
    runner.run_agent(root["id"])

    # a summarizer ran, and the child's prompt carries the summary prefix
    roles = [a["role"] for a in ctx.db.list_swarm_agents(sid)]
    assert "summarizer" in roles
    child_calls = [c for c in client.calls
                   if any("do sub piece" in m["content"] for m in c["messages"])
                   and any("ROLE: coding_agent" in m["content"] for m in c["messages"])]
    assert child_calls
    blob = "\n".join(m["content"] for m in child_calls[0]["messages"])
    assert "[SUMMARY OF EARLIER CONVERSATION]" in blob
