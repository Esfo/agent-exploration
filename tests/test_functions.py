from conftest import make_runtime

from swarm import functions
from swarm.substitution import Context


def test_extract_code_blocks_recognizes_languages():
    text = "```python\nprint(1)\n```\nand\n```rb\nputs 2\n```\n```nonsense\nx\n```"
    blocks = functions.extract_code_blocks(text)
    assert blocks == [("python", "print(1)\n"), ("ruby", "puts 2\n")]


def test_extract_finished_output():
    text = "thinking out loud\nFINISHED OUTPUT\nthe real result\nline two"
    assert functions.extract_finished_output(text) == "the real result\nline two"
    assert functions.extract_finished_output("no marker here") == "no marker here"


def test_tools_only_for_code_roles():
    assert functions.has_tools("coding")
    assert functions.has_tools("math")
    assert not functions.has_tools("philosophizing")


def test_council_rhetoric_and_final_output(project):
    rt = make_runtime(project, client=None)
    ctx = Context(instr=rt.instr,
                  rhetoric=[("coding", "wrote it"), ("testing", "tested it")],
                  final_outputs=[("coding (agent_0001)", "line a\nline b")])
    rhet = functions.council_rhetoric(ctx)
    assert "coding:\nwrote it" in rhet and "testing:\ntested it" in rhet
    fo = functions.final_output(ctx)
    assert "coding (agent_0001)" in fo and "line 1: line a" in fo and "line 2: line b" in fo


def test_failure_aggregation_excludes_self(project):
    rt = make_runtime(project, client=None)
    ctx = Context(instr=rt.instr,
                  failure_votes=[("coding_2", "looks good\nI vote FINISHED"),
                                 ("math_3", "needs work\nI vote INCOMPLETE")])
    out = functions.failure_aggregation(ctx)
    assert "coding_2:\nlooks good\nI vote FINISHED" in out
    assert "math_3:\nneeds work\nI vote INCOMPLETE" in out
    # empty -> placeholder
    assert "no other votes" in functions.failure_aggregation(Context(instr=rt.instr))


def test_list_agent_types(project):
    rt = make_runtime(project, client=None)
    out = functions.list_agent_types(Context(instr=rt.instr))
    for t in ("coding", "math", "optimization", "philosophizing", "testing"):
        assert f"{t}:" in out
