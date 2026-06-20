from conftest import MockClient, make_runtime

from swarm.zipper import Document, run_zipper


def test_document_retain_and_insert():
    doc = Document([("coding (a1)", "def f():\n    return 1"),
                    ("philosophizing (a2)", "intent: compute one\nnote: trivial")])
    doc.apply("INSERT TEXT ```python")
    doc.apply("RETAIN coding")
    doc.apply("INSERT TEXT ```")
    doc.apply("INSERT philosophizing line 1 to 1 PREPEND # ")
    rendered = doc.render()
    assert rendered.splitlines() == [
        "```python", "def f():", "    return 1", "```", "# intent: compute one"]


def test_run_zipper_workflow(project):
    def script(last_user, system, n):
        if "finalizing the work of a council" in last_user:   # zipper/initiate
            return "RETAIN coding"
        if "Is this the final response" in last_user:         # zipper/finish
            return "Looks good. CONFIRM"
        return "RETAIN coding"
    rt = make_runtime(project, MockClient(script))
    payload = run_zipper(rt, [("coding (a1)", "print('done')")], inherited=[],
                         task="build it", task_truncated="build it")
    assert payload.startswith("FINISHED OUTPUT")
    assert "print('done')" in payload
