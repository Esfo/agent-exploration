"""Finish-gate check runner: auto checks + gate blocking/passing."""
from pathlib import Path

from swarm import ids
from swarm.checks import AUTO_CHECKS, run_gate, available_auto_keys
from swarm.instructions import parse_instruction_file
from tests.conftest import MockClient, make_runtime


def _agent(ctx, role="code"):
    ids._counters.clear()
    sid = ids.next_id("swarm")
    ctx.db.create_swarm(sid, "g")
    return ctx.create_root(sid, role, "Root", "do work")


# ---------- tag parsing ----------
def test_auto_tag_parsed_and_stripped(tmp_path):
    p = tmp_path / "x.txt"
    p.write_text("MODEL: <PLACEHOLDER_OLLAMA_MODEL>\nPURPOSE: p\n"
                 "001. A file was created. [[auto:created_a_file]]\n"
                 "002. The code is readable.\n")
    inst = parse_instruction_file(p)
    assert inst.checks[0].auto_key == "created_a_file"
    assert inst.checks[0].text == "A file was created."   # tag stripped
    assert inst.checks[1].auto_key is None
    assert "[[auto" not in inst.render()                  # not shown to model


# ---------- deterministic checks ----------
def test_created_a_file_check(project):
    ctx, _ = make_runtime(project, MockClient(lambda *_: ""))
    from swarm.tools import files
    agent = _agent(ctx)
    passed, _ = AUTO_CHECKS["created_a_file"](ctx, agent["id"])
    assert passed is False
    files.write_file(ctx, agent["id"], {"path": "a.py", "content": "x=1\n"})
    passed, _ = AUTO_CHECKS["created_a_file"](ctx, agent["id"])
    assert passed is True


def test_validation_passed_check(project):
    ctx, _ = make_runtime(project, MockClient(lambda *_: ""))
    from swarm.tools import python_exec
    agent = _agent(ctx)
    assert AUTO_CHECKS["validation_passed"](ctx, agent["id"])[0] is False
    res = python_exec.execute(ctx, agent["id"], {
        "reason": "v", "expected_result": "ok", "destructive_risk_answer": "none",
        "code": "print('ok')"})
    ctx.db.save_tool_call(agent["id"], "python", {}, res["status"], res)  # as the loop does
    assert AUTO_CHECKS["validation_passed"](ctx, agent["id"])[0] is True


def test_tests_present_check(project):
    ctx, _ = make_runtime(project, MockClient(lambda *_: ""))
    from swarm.tools import files
    agent = _agent(ctx)
    files.write_file(ctx, agent["id"], {"path": "mod.py", "content": "x=1\n"})
    assert AUTO_CHECKS["tests_present"](ctx, agent["id"])[0] is False
    files.write_file(ctx, agent["id"], {"path": "test_mod.py", "content": "def test_x():\n    assert True\n"})
    assert AUTO_CHECKS["tests_present"](ctx, agent["id"])[0] is True


def test_available_auto_keys():
    keys = available_auto_keys()
    assert "created_a_file" in keys and "validation_passed" in keys


# ---------- gate integration ----------
def _enable_gate(project, model_eval=False):
    sp = project / "settings" / "main.settings"
    txt = sp.read_text().replace("CHECK_GATE_ENABLED=false", "CHECK_GATE_ENABLED=true")
    if not model_eval:
        txt = txt.replace("CHECK_GATE_MODEL_EVAL=true", "CHECK_GATE_MODEL_EVAL=false")
    sp.write_text(txt)


def test_gate_blocks_finish_until_check_met(project):
    # coding.txt = one deterministic check requiring a created file.
    (project / "instructions" / "coding.txt").write_text(
        "MODEL: <PLACEHOLDER_OLLAMA_MODEL>\nPURPOSE: code checks\n"
        "001. A file was created for the deliverable. [[auto:created_a_file]]\n")
    _enable_gate(project)
    ids._counters.clear()
    state = {"n": 0}

    def script(last_user, model, n):
        state["n"] += 1
        if state["n"] == 1:
            return '<<tool:finish>>{"status":"complete","summary":"done (but no file yet)"}<</tool>>'
        if "Finish blocked by a check" in last_user:
            return '<<tool:write_file>>{"path":"deliverable.py","content":"def f():\\n    return 1\\n"}<</tool>>'
        return '<<tool:finish>>{"status":"complete","summary":"file written"}<</tool>>'

    ctx, runner = make_runtime(project, MockClient(script))
    agent = _agent(ctx, "code")
    result = runner.run_agent(agent["id"])

    assert result["status"] == "complete"
    assert (Path(agent["assigned_directory"]) / "deliverable.py").exists()
    # the gate forced at least one extra round trip
    assert state["n"] >= 3


def test_gate_blocks_permanently_after_max_attempts(project):
    (project / "instructions" / "coding.txt").write_text(
        "MODEL: <PLACEHOLDER_OLLAMA_MODEL>\nPURPOSE: code checks\n"
        "001. A file was created. [[auto:created_a_file]]\n")
    _enable_gate(project)
    ids._counters.clear()

    def script(last_user, model, n):
        # Always claims complete, never writes a file -> gate keeps failing.
        return '<<tool:finish>>{"status":"complete","summary":"lying about completion"}<</tool>>'

    ctx, runner = make_runtime(project, MockClient(script))
    agent = _agent(ctx, "code")
    result = runner.run_agent(agent["id"])
    assert result["status"] == "blocked"
    assert result["failure"] == "check_gate_failed"
    assert "created" in result["note"].lower()


def test_gate_allows_blocked_status_through(project):
    (project / "instructions" / "coding.txt").write_text(
        "MODEL: <PLACEHOLDER_OLLAMA_MODEL>\nPURPOSE: code checks\n"
        "001. A file was created. [[auto:created_a_file]]\n")
    _enable_gate(project)
    ids._counters.clear()

    def script(last_user, model, n):
        # Agent honestly defers — gate must NOT run on a "blocked" finish.
        return '<<tool:finish>>{"status":"blocked","note":"cannot do this without X"}<</tool>>'

    ctx, runner = make_runtime(project, MockClient(script))
    agent = _agent(ctx, "code")
    result = runner.run_agent(agent["id"])
    assert result["status"] == "blocked"
    assert result.get("failure") != "check_gate_failed"  # passed straight through
