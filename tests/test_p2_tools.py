"""Prototype 2: guards, file tools, and sandboxed execution."""
from pathlib import Path

from swarm import ids
from swarm.runtime_guards import path_guard
from swarm.runtime_guards.command_guard import check_command
from tests.conftest import MockClient, make_runtime


def _root_agent(ctx):
    ids._counters.clear()
    sid = ids.next_id("swarm")
    ctx.db.create_swarm(sid, "goal")
    return ctx.create_root(sid, "code", "Root", "do work")


# ---------- path guard ----------
def test_path_guard_confines(tmp_path):
    base = tmp_path / "work"
    base.mkdir()
    ok = path_guard.check("a/b.py", base=base, allowed_roots=[base], op="write")
    assert str(ok).startswith(str(base))


def test_path_guard_blocks_escape(tmp_path):
    base = tmp_path / "work"
    base.mkdir()
    import pytest
    with pytest.raises(path_guard.PathDenied):
        path_guard.check("../../etc/passwd", base=base, allowed_roots=[base], op="write")


def test_path_guard_blocks_absolute(tmp_path):
    base = tmp_path / "work"
    base.mkdir()
    import pytest
    with pytest.raises(path_guard.PathDenied):
        path_guard.check("/etc/passwd", base=base, allowed_roots=[base], op="read")


# ---------- command guard ----------
def test_command_guard_blocks_rm_rf_root():
    r = check_command("rm -rf /", {"reason": "x", "expected_result": "y",
                                   "destructive_risk_answer": "z"}, network_enabled=False)
    assert not r.allowed and r.reasons


def test_command_guard_blocks_sudo():
    r = check_command("sudo rm file", {"reason": "x", "expected_result": "y",
                                       "destructive_risk_answer": "z"}, network_enabled=False)
    assert not r.allowed


def test_command_guard_requires_fields():
    r = check_command("ls", {}, network_enabled=False)
    assert not r.allowed
    assert "reason" in r.missing_fields


def test_command_guard_network_when_disabled():
    r = check_command("curl http://x", {"reason": "a", "expected_result": "b",
                                        "destructive_risk_answer": "c"}, network_enabled=False)
    assert not r.allowed


def test_command_guard_allows_safe():
    r = check_command("python -m pytest", {"reason": "run tests", "expected_result": "pass",
                                           "destructive_risk_answer": "none"}, network_enabled=False)
    assert r.allowed


# ---------- file tools ----------
def test_write_and_read_file(project):
    ctx, _ = make_runtime(project, MockClient(lambda *_: ""))
    from swarm.tools import files
    agent = _root_agent(ctx)
    w = files.write_file(ctx, agent["id"], {"path": "hello.py", "content": "print('hi')\n"})
    assert w["status"] == "ok" and w["action"] == "created"
    assert Path(w["path"]).read_text() == "print('hi')\n"
    r = files.read_file(ctx, agent["id"], {"path": "hello.py"})
    assert r["status"] == "ok" and "print('hi')" in r["content"]


def test_write_outside_dir_denied(project):
    ctx, _ = make_runtime(project, MockClient(lambda *_: ""))
    from swarm.tools import files
    agent = _root_agent(ctx)
    w = files.write_file(ctx, agent["id"], {"path": "../../escape.py", "content": "x"})
    assert w["status"] == "error" and w["failure"] == "path_denied"


def test_soft_delete(project):
    ctx, _ = make_runtime(project, MockClient(lambda *_: ""))
    from swarm.tools import files
    agent = _root_agent(ctx)
    files.write_file(ctx, agent["id"], {"path": "junk.py", "content": "x"})
    d = files.delete_file(ctx, agent["id"], {"path": "junk.py", "reason": "cleanup"})
    assert d["status"] == "ok" and d["soft_deleted_to"]
    assert Path(d["soft_deleted_to"]).exists()


# ---------- execution ----------
def test_python_execution(project):
    ctx, _ = make_runtime(project, MockClient(lambda *_: ""))
    from swarm.tools import python_exec
    agent = _root_agent(ctx)
    res = python_exec.execute(ctx, agent["id"], {
        "reason": "compute", "expected_result": "prints 4",
        "destructive_risk_answer": "none", "code": "print(2+2)",
    })
    assert res["status"] == "ok"
    assert res["exit_code"] == 0
    assert "4" in res["stdout"]


def test_python_blocked_without_fields(project):
    ctx, _ = make_runtime(project, MockClient(lambda *_: ""))
    from swarm.tools import python_exec
    agent = _root_agent(ctx)
    res = python_exec.execute(ctx, agent["id"], {"code": "print(1)"})
    assert res["status"] == "blocked"
    assert res["failure"] == "command_guard_blocked"


def test_shell_execution_and_file_roundtrip(project):
    ctx, _ = make_runtime(project, MockClient(lambda *_: ""))
    from swarm.tools import files, shell_exec
    agent = _root_agent(ctx)
    files.write_file(ctx, agent["id"], {"path": "data.txt", "content": "alpha\n"})
    res = shell_exec.execute(ctx, agent["id"], {
        "reason": "read file", "expected_result": "alpha", "destructive_risk_answer": "none",
        "command": "cat data.txt",
    })
    assert res["status"] == "ok"
    assert "alpha" in res["stdout"]


def test_full_loop_writes_real_file(project):
    """The model writes a file then verifies it with python, then finishes."""
    ids._counters.clear()
    state = {"n": 0}

    def script(last_user, model, n):
        state["n"] += 1
        if state["n"] == 1:
            return ('<<tool:write_file>>{"path":"rev.py","content":"def rev(s):\\n    return s[::-1]\\n"}<</tool>>')
        if state["n"] == 2:
            return ('<<tool:python>>{"reason":"verify","expected_result":"olleh","destructive_risk_answer":"none",'
                    '"code":"import rev; print(rev.rev(\'hello\'))"}<</tool>>')
        return '<<tool:finish>>{"status":"complete","summary":"wrote rev.py","files_created":["rev.py"]}<</tool>>'

    ctx, runner = make_runtime(project, MockClient(script))
    sid = ids.next_id("swarm")
    ctx.db.create_swarm(sid, "reverse string")
    root = ctx.create_root(sid, "code", "Root", "write a reverse function")
    result = runner.run_agent(root["id"])
    assert result["status"] == "complete"
    work = Path(root["assigned_directory"])
    assert (work / "rev.py").exists()
    assert "def rev" in (work / "rev.py").read_text()
