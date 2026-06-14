"""Persistent terminal sessions + cwd guard (subprocess backend)."""
from swarm import ids
from swarm.runtime_guards import cwd_guard
from tests.conftest import MockClient, make_runtime


def _agent(ctx):
    ids._counters.clear()
    sid = ids.next_id("swarm")
    ctx.db.create_swarm(sid, "g")
    return ctx.create_root(sid, "code", "Root", "work")


# ---------- cwd guard ----------
def test_cwd_guard_within():
    assert cwd_guard.within("/a/b/c", "/a/b")
    assert cwd_guard.within("/a/b", "/a/b")
    assert not cwd_guard.within("/a/x", "/a/b")
    assert not cwd_guard.within("/a", "/a/b")


def test_cwd_guard_relative():
    assert cwd_guard.relative("/a/b", "/a/b") == "."
    assert cwd_guard.relative("/a/b/sub", "/a/b") == "sub"
    assert cwd_guard.relative("/a/c", "/a/b") is None


# ---------- terminal lifecycle ----------
def test_open_run_close(project):
    ctx, _ = make_runtime(project, MockClient(lambda *_: ""))
    from swarm.tools import terminals
    agent = _agent(ctx)
    opened = terminals.open_terminal(ctx, agent["id"], {"purpose": "tests"})
    assert opened["status"] == "ok"
    tid = opened["terminal_id"]

    res = terminals.terminal_command(ctx, agent["id"], {
        "terminal_id": tid, "command": "echo hello",
        "reason": "smoke", "expected_result": "hello", "destructive_risk_answer": "none",
    })
    assert res["status"] == "ok"
    assert "hello" in res["stdout"]
    assert "__CWD__" not in res["stdout"]  # marker stripped
    assert res["cwd_guard_passed"] is True

    closed = terminals.close_terminal(ctx, agent["id"], {"terminal_id": tid})
    assert closed["status"] == "ok"


def test_terminal_requires_open_session(project):
    ctx, _ = make_runtime(project, MockClient(lambda *_: ""))
    from swarm.tools import terminals
    agent = _agent(ctx)
    res = terminals.terminal_command(ctx, agent["id"], {
        "terminal_id": "terminal_9999", "command": "echo x",
        "reason": "r", "expected_result": "e", "destructive_risk_answer": "n",
    })
    assert res["status"] == "error"
    assert res["failure"] == "terminal_create_failed"


def test_terminal_blocks_missing_fields(project):
    ctx, _ = make_runtime(project, MockClient(lambda *_: ""))
    from swarm.tools import terminals
    agent = _agent(ctx)
    tid = terminals.open_terminal(ctx, agent["id"], {})["terminal_id"]
    res = terminals.terminal_command(ctx, agent["id"], {"terminal_id": tid, "command": "echo x"})
    assert res["status"] == "blocked"
    assert "reason" in res["missing_fields"]


def test_terminal_cwd_logged(project):
    ctx, _ = make_runtime(project, MockClient(lambda *_: ""))
    from swarm.tools import terminals
    agent = _agent(ctx)
    tid = terminals.open_terminal(ctx, agent["id"], {})["terminal_id"]
    terminals.terminal_command(ctx, agent["id"], {
        "terminal_id": tid, "command": "pwd",
        "reason": "r", "expected_result": "e", "destructive_risk_answer": "n",
    })
    row = ctx.db.conn.execute(
        "SELECT * FROM terminal_commands WHERE terminal_id=?", (tid,)
    ).fetchone()
    assert row is not None
    assert row["cwd_guard_passed"] == 1
