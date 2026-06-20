from conftest import make_runtime

from swarm.sandbox import format_result, run_code


def test_run_python_in_subprocess_sandbox(project, tmp_path):
    rt = make_runtime(project, client=None)
    result = run_code(rt.executor, "python", "print('hello sandbox')",
                      rt.agent_dir("agent_x"))
    assert result is not None
    assert "hello sandbox" in format_result(result)


def test_unknown_language_returns_none(project):
    rt = make_runtime(project, client=None)
    assert run_code(rt.executor, "brainfuck", "+++", rt.agent_dir("agent_y")) is None
    assert "no runnable code block" in format_result(None)
