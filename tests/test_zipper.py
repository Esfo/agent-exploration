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


def test_document_positional_insert_renumbers():
    doc = Document([("coding (a1)", "line A\nline B\nline C")])
    doc.apply("RETAIN coding")               # A, B, C
    doc.apply("INSERT line 2 X")             # A, X, B, C
    assert doc.render().splitlines() == ["line A", "X", "line B", "line C"]
    # Inserting twice at the same line: the first ends up one below the second.
    doc.apply("INSERT line 2 first\nINSERT line 2 second")
    assert doc.render().splitlines() == [
        "line A", "second", "first", "X", "line B", "line C"]


def test_document_insert_code_fence_at_position():
    doc = Document([("coding (a1)", "print('hi')")])
    doc.apply("RETAIN coding")
    doc.apply("INSERT line 1 ```python")
    doc.apply("INSERT line 3 ```")
    assert doc.render().splitlines() == ["```python", "print('hi')", "```"]


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
