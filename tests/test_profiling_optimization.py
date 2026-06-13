"""Profiling + optimization tools (subprocess backend)."""
from swarm import ids
from tests.conftest import MockClient, make_runtime


def _agent(ctx, role="profiler"):
    ids._counters.clear()
    sid = ids.next_id("swarm")
    ctx.db.create_swarm(sid, "g")
    return ctx.create_root(sid, role, "Root", "work")


def test_profile_python_workload(project):
    ctx, _ = make_runtime(project, MockClient(lambda *_: ""))
    from swarm.tools import files, profiling
    agent = _agent(ctx)
    files.write_file(ctx, agent["id"], {"path": "scan.py",
                     "content": "def f():\n    return sum(range(100000))\nf()\n"})
    res = profiling.execute(ctx, agent["id"], {
        "target": "scan", "language": "python", "command": "python scan.py",
        "reason": "measure", "expected_result": "runs", "destructive_risk_answer": "none",
    })
    assert res["status"] == "ok"
    assert res["baseline_runtime_ms"] >= 0
    assert res["profiling_report_id"].startswith("profile_")
    # cProfile produced bottleneck lines
    assert isinstance(res["top_bottlenecks"], list)
    row = ctx.db.conn.execute("SELECT * FROM profiling_reports WHERE id=?",
                              (res["profiling_report_id"],)).fetchone()
    assert row is not None


def test_optimize_requires_baseline(project):
    ctx, _ = make_runtime(project, MockClient(lambda *_: ""))
    from swarm.tools import optimization
    agent = _agent(ctx, "optimizer")
    res = optimization.execute(ctx, agent["id"], {"target": "x", "goal": "speed up"})
    assert res["status"] == "blocked"
    assert res["failure"] == "optimization_failed"


def test_optimize_with_validation(project):
    ctx, _ = make_runtime(project, MockClient(lambda *_: ""))
    from swarm.tools import optimization
    agent = _agent(ctx, "optimizer")
    res = optimization.execute(ctx, agent["id"], {
        "target": "x", "before_runtime_ms": 1000, "goal": "cache results",
        "validation_command": "python -c \"print('ok')\"",
        "reason": "validate", "expected_result": "ok", "destructive_risk_answer": "none",
    })
    assert res["status"] == "ok"
    assert res["validation"] == "passed"
    assert res["before_runtime_ms"] == 1000
    assert res["after_runtime_ms"] is not None
    assert res["improvement"] is not None


def test_optimize_uses_profiling_report(project):
    ctx, _ = make_runtime(project, MockClient(lambda *_: ""))
    from swarm.tools import files, profiling, optimization
    agent = _agent(ctx, "optimizer")
    files.write_file(ctx, agent["id"], {"path": "w.py", "content": "print(1)\n"})
    prof = profiling.execute(ctx, agent["id"], {
        "target": "w", "language": "python", "command": "python w.py",
        "reason": "m", "expected_result": "1", "destructive_risk_answer": "none"})
    res = optimization.execute(ctx, agent["id"], {
        "target": "w", "profiling_report_id": prof["profiling_report_id"], "goal": "x"})
    # no validation command -> still records, before pulled from profiling report
    assert res["status"] == "ok"
    assert res["before_runtime_ms"] == prof["baseline_runtime_ms"]
