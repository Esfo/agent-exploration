from conftest import make_runtime

from swarm.substitution import Context, resolve


def _ctx(rt, **kw):
    return Context(instr=rt.instr, **kw)


def test_scalar_arrows(project):
    rt = make_runtime(project, client=None)
    ctx = _ctx(rt, agent_type="coding", task="Build the parser",
               task_truncated="build parser", inherited_goal="ship the tool")
    out = resolve(">>AGENT_TYPE<< / >>TASK<< / >>TASK_TRUNCATED<< / >>INHERITED_GOAL<<", ctx)
    assert out == "coding / Build the parser / build parser / ship the tool"


def test_inherited_goal_with_space(project):
    rt = make_runtime(project, client=None)
    ctx = _ctx(rt, inherited_goal="the goal")
    assert resolve(">>INHERITED GOAL<<", ctx) == "the goal"


def test_purpose_arrow_reads_agent_file(project):
    rt = make_runtime(project, client=None)
    ctx = _ctx(rt, agent_type="coding")
    out = resolve(">>PURPOSE<<", ctx)
    assert "coding agent" in out.lower()


def test_query_and_function_arrows(project):
    rt = make_runtime(project, client=None)
    ctx = _ctx(rt, agent_type="coding")
    spawning = resolve(">>SPAWNING<<", ctx)
    # SPAWNING embeds >>LIST_AGENT_TYPES<<, which must be expanded recursively.
    assert "coding:" in spawning
    assert "philosophizing:" in spawning
    assert ">>" not in spawning  # all arrows resolved


def test_unknown_arrow_left_intact(project):
    rt = make_runtime(project, client=None)
    assert resolve(">>NOT_A_REAL_ARROW<<", _ctx(rt)) == ">>NOT_A_REAL_ARROW<<"
