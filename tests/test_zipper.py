"""Zipper process: integrate converged deliverables into PROJECT_DIR + docs."""
from pathlib import Path

from swarm import ids
from swarm.zipper import run_zipper, _parse_yes
from tests.conftest import MockClient, make_runtime


def test_parse_yes():
    assert _parse_yes("YES") is True
    assert _parse_yes("yes, integrate it") is True
    assert _parse_yes("NO") is False
    assert _parse_yes("maybe") is False
    assert _parse_yes("") is False


def _agent_with_file(ctx, root, name, content):
    a = ctx.create_child(parent=root, title="impl", task="t", role="coding_agent",
                         done_condition="", suggested_model=None, priority=1)
    work = Path(a["assigned_directory"])
    work.mkdir(parents=True, exist_ok=True)
    (work / name).write_text(content, encoding="utf-8")
    return a


def test_zipper_integrates_yes_files(project):
    ids._counters.clear()

    def script(last_user, model, n):
        return "YES"  # the gate approves every artifact

    ctx, _ = make_runtime(project, MockClient(script))
    sid = ids.next_id("swarm")
    ctx.db.create_swarm(sid, "g")
    root = ctx.create_root(sid, "chat_agent", "Root", "build add()")
    a = _agent_with_file(ctx, root, "add.py", "def add(a, b):\n    return a + b\n")
    zipper = ctx.create_child(parent=root, title="zip", task="finalize",
                              role="zipper_agent", done_condition="",
                              suggested_model=None, priority=9)

    src = Path(a["assigned_directory"]) / "add.py"
    res = run_zipper(ctx, zipper, [a], task_list="- impl", goal="build add()")

    project_dir = ctx.settings.path("PROJECT_DIR")
    # a coding_agent's .py lands in code/, and is MOVED (source no longer exists)
    assert (project_dir / "code" / "add.py").exists()
    assert (project_dir / "code" / "add.py").read_text().startswith("def add")
    assert not src.exists()
    assert len(res.integrated) == 1
    # minimal manifest references the categorized path with its blurb
    manifest = Path(res.doc_path)
    assert manifest.exists()
    body = manifest.read_text()
    assert "code/add.py" in body
    assert "here's the code" in body


def test_zipper_skips_no_files(project):
    ids._counters.clear()

    def script(last_user, model, n):
        return "NO"  # the gate rejects everything

    ctx, _ = make_runtime(project, MockClient(script))
    sid = ids.next_id("swarm")
    ctx.db.create_swarm(sid, "g")
    root = ctx.create_root(sid, "chat_agent", "Root", "build")
    a = _agent_with_file(ctx, root, "scratch.txt", "throwaway")
    zipper = ctx.create_child(parent=root, title="zip", task="finalize",
                              role="zipper_agent", done_condition="",
                              suggested_model=None, priority=9)

    res = run_zipper(ctx, zipper, [a], goal="build")

    project_dir = ctx.settings.path("PROJECT_DIR")
    assert not (project_dir / "docs" / "scratch.txt").exists()
    assert res.integrated == []
    assert len(res.skipped) == 1


def test_zipper_skips_gitkeep_and_pyc(project):
    ids._counters.clear()

    def script(last_user, model, n):
        return "YES"

    ctx, _ = make_runtime(project, MockClient(script))
    sid = ids.next_id("swarm")
    ctx.db.create_swarm(sid, "g")
    root = ctx.create_root(sid, "chat_agent", "Root", "build")
    a = ctx.create_child(parent=root, title="impl", task="t", role="coding_agent",
                         done_condition="", suggested_model=None, priority=1)
    work = Path(a["assigned_directory"])
    work.mkdir(parents=True, exist_ok=True)
    (work / ".gitkeep").write_text("")
    (work / "mod.pyc").write_text("x")
    (work / "real.py").write_text("print(1)\n")

    res = run_zipper(ctx, zipper=ctx.create_child(
        parent=root, title="zip", task="f", role="zipper_agent",
        done_condition="", suggested_model=None, priority=9), agents=[a], goal="build")

    names = {Path(p).name for p in res.integrated}
    assert names == {"real.py"}  # .gitkeep and .pyc never integrated


def test_zipper_categorizes_by_role_and_target_dir(project, tmp_path):
    ids._counters.clear()

    def script(last_user, model, n):
        return "YES"

    ctx, _ = make_runtime(project, MockClient(script))
    sid = ids.next_id("swarm")
    ctx.db.create_swarm(sid, "g")
    root = ctx.create_root(sid, "chat_agent", "Root", "build")
    coder = _agent_with_file(ctx, root, "lib.py", "x=1\n")
    researcher = _agent_with_file2(ctx, root, "researcher", "findings.md", "# notes\n")
    zipper = ctx.create_child(parent=root, title="zip", task="f", role="zipper_agent",
                              done_condition="", suggested_model=None, priority=9)

    target = tmp_path / "sub_project"
    res = run_zipper(ctx, zipper, [coder, researcher], goal="g", target_dir=target)

    # researcher output -> research/ (by role), coder .py -> code/
    assert (target / "code" / "lib.py").exists()
    assert (target / "research" / "findings.md").exists()
    assert len(res.integrated) == 2
    body = (target / "README.md").read_text()
    assert "here's the code" in body and "here's the research" in body


def _agent_with_file2(ctx, root, role, name, content):
    a = ctx.create_child(parent=root, title=role, task="t", role=role,
                         done_condition="", suggested_model=None, priority=1)
    work = Path(a["assigned_directory"])
    work.mkdir(parents=True, exist_ok=True)
    (work / name).write_text(content, encoding="utf-8")
    return a
