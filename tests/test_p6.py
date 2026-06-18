"""P6: context summarization, memory store + toggles, branching."""
from swarm import ids
from swarm.token_budget import summarize_to_fit, estimate_messages, safe_input_budget, ContextLimitReached
from swarm.memory import MemoryStore
from swarm.branching import BranchManager
from tests.conftest import MockClient, make_runtime
import pytest


# ---------- summarization ----------
def test_summarize_keeps_head_and_recent():
    sys = {"role": "system", "content": "S" * 100}
    packet = {"role": "user", "content": "P" * 100}
    middle = [{"role": "assistant", "content": "M" * 4000} for _ in range(20)]
    recent = {"role": "user", "content": "RECENT-MARKER"}
    messages = [sys, packet] + middle + [recent]

    out = summarize_to_fit(messages, num_ctx=4096, num_predict=512, safety_margin=128,
                           max_summary_tokens=256)
    assert out[0] is sys
    assert out[1] is packet
    assert out[-1] is recent  # most recent preserved
    assert any("earlier context summarized" in m["content"] for m in out)
    budget = safe_input_budget(4096, 512, 128)
    assert estimate_messages(out) <= budget


def test_summarize_noop_when_fits():
    messages = [{"role": "system", "content": "hi"}, {"role": "user", "content": "there"}]
    out = summarize_to_fit(messages, 8192, 2048, 256, 2048)
    assert out is messages


def test_summarize_raises_when_head_too_big():
    huge = {"role": "system", "content": "X" * 100000}
    packet = {"role": "user", "content": "Y" * 100000}
    with pytest.raises(ContextLimitReached):
        summarize_to_fit([huge, packet], num_ctx=1024, num_predict=256, safety_margin=64,
                         max_summary_tokens=128)


# ---------- memory ----------
def test_memory_add_toggle_relevant(project):
    ctx, _ = make_runtime(project, MockClient(lambda *_: ""))
    mem = MemoryStore(ctx.db)
    m1 = mem.add("always use pathlib for filesystem paths", scope="global", tags="files,path")
    m2 = mem.add("the deploy server is flaky on fridays", scope="global")
    rel = mem.relevant(role="coding_agent", task="write code that resolves filesystem path")
    assert any(m["id"] == m1 for m in rel)
    # disable m1 -> no longer surfaced
    mem.set_enabled(m1, False)
    rel2 = mem.relevant(role="coding_agent", task="resolve filesystem path")
    assert not any(m["id"] == m1 for m in rel2)


def test_memory_scope_filter(project):
    ctx, _ = make_runtime(project, MockClient(lambda *_: ""))
    mem = MemoryStore(ctx.db)
    mem.add("reviewer-only note", scope="reviewer")
    rel_code = mem.relevant(role="coding_agent", task="anything")
    assert not any("reviewer-only" in m["text"] for m in rel_code)
    rel_rev = mem.relevant(role="reviewer", task="anything")
    assert any("reviewer-only" in m["text"] for m in rel_rev)


def test_memory_injected_into_context(project):
    """An enabled memory shows up in the model's prompt."""
    ids._counters.clear()
    seen = {}

    def script(last_user, model, n):
        seen["prompt"] = last_user
        return '<<tool:finish>>{"status":"complete","summary":"done"}<</tool>>'

    client = MockClient(script)
    ctx, runner = make_runtime(project, client)
    ctx.memory = MemoryStore(ctx.db)
    ctx.memory.add("REMEMBER-THIS-FACT", scope="global")
    sid = ids.next_id("swarm")
    ctx.db.create_swarm(sid, "g")
    root = ctx.create_root(sid, "coding_agent", "Root", "do work")
    runner.run_agent(root["id"])
    assert "REMEMBER-THIS-FACT" in seen["prompt"]


# ---------- branching ----------
def test_branch_copies_goal_and_messages(project):
    ids._counters.clear()
    ctx, _ = make_runtime(project, MockClient(lambda *_: ""))
    sid = ids.next_id("swarm")
    ctx.db.create_swarm(sid, "original goal")
    root = ctx.create_root(sid, "chat_agent", "Root", "original goal")
    ctx.db.save_message(root["id"], "user", "first message")
    ctx.db.save_message(root["id"], "assistant", "second message")

    bm = BranchManager(ctx.db)
    res = bm.branch(sid, note="try variation")
    assert res["status"] == "ok"
    assert res["copied_messages"] == 2
    new_root_msgs = ctx.db.get_messages(res["root_agent_id"])
    assert [m["content"] for m in new_root_msgs] == ["first message", "second message"]
    new_swarm = ctx.db.get_swarm(res["branch_swarm_id"])
    assert "original goal" in new_swarm["user_goal"]
    assert "try variation" in new_swarm["user_goal"]


def test_branch_at_message_point(project):
    ids._counters.clear()
    ctx, _ = make_runtime(project, MockClient(lambda *_: ""))
    sid = ids.next_id("swarm")
    ctx.db.create_swarm(sid, "g")
    root = ctx.create_root(sid, "chat_agent", "Root", "g")
    ctx.db.save_message(root["id"], "user", "m1")
    ctx.db.save_message(root["id"], "assistant", "m2")
    ctx.db.save_message(root["id"], "user", "m3")
    rows = ctx.db.get_messages(root["id"])
    cutoff = rows[1]["id"]  # only m1, m2

    bm = BranchManager(ctx.db)
    res = bm.branch(sid, at_message_id=cutoff)
    assert res["copied_messages"] == 2
