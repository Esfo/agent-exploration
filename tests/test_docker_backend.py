"""Docker backend argv construction (does not require a running daemon)."""
from pathlib import Path

from swarm.sandbox.docker_backend import DockerExecutor
from swarm.settings import Settings
from tests.conftest import REPO


def _settings(project):
    return Settings.load(project / "settings" / "main.settings")


def test_argv_has_isolation_flags(project):
    ex = DockerExecutor(_settings(project))
    work = project / "workspace" / "agents" / "agent_0001" / "work"
    work.mkdir(parents=True, exist_ok=True)
    argv = ex.build_run_argv(work, ["python", "/agent/.runtime/x.py"])
    s = " ".join(argv)
    assert "docker run --rm" in s
    assert "--network none" in s
    assert "--cap-drop ALL" in s
    assert "--security-opt no-new-privileges" in s
    assert "--pids-limit 256" in s
    assert "--memory 2048m" in s
    assert f"{work.resolve()}:/agent:rw" in s
    assert "-w /agent" in s
    assert argv[-2:] == ["python", "/agent/.runtime/x.py"]
    assert "python:3.12-slim" in argv


def test_argv_read_only_root(project):
    ex = DockerExecutor(_settings(project))
    work = project / "workspace" / "agents" / "agent_0002" / "work"
    work.mkdir(parents=True, exist_ok=True)
    argv = ex.build_run_argv(work, ["sh", "-c", "echo hi"])
    s = " ".join(argv)
    assert "--read-only" in s
    assert "/tmp:rw" in s


def test_select_executor_falls_back_without_docker(project, monkeypatch):
    import swarm.sandbox as sb
    monkeypatch.setattr(sb, "docker_available", lambda: False)
    ex = sb.select_executor(_settings(project))
    assert ex.backend == "subprocess"


def test_select_executor_uses_docker_when_available(project, monkeypatch):
    import swarm.sandbox as sb
    monkeypatch.setattr(sb, "docker_available", lambda: True)
    ex = sb.select_executor(_settings(project))
    assert ex.backend == "docker"
