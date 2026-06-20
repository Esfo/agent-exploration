from conftest import make_runtime

from swarm.sandbox import SubprocessExecutor
from swarm.sandbox.docker_backend import DockerExecutor
from swarm.settings import Settings


def _settings(project):
    return Settings.load(project / "settings" / "main.settings")


def test_throwaway_run_argv_is_hardened(project):
    d = DockerExecutor(_settings(project))
    argv = d.build_run_argv("/tmp/agent", ["python", "x.py"])
    assert argv[:3] == ["docker", "run", "--rm"]
    for flag in ("--network", "--cap-drop", "--security-opt", "--read-only", "--pids-limit"):
        assert flag in argv
    assert argv[-2:] == ["python", "x.py"]
    assert d.image in argv


def test_session_daemon_mounts_agents_root(project):
    d = DockerExecutor(_settings(project))
    # The one session container mounts the agents ROOT (parent), not one agent.
    daemon = d.build_daemon_argv("/work/agents", "rls_sbx_0001")
    assert daemon[:4] == ["docker", "run", "-d", "--rm"]
    assert "--name" in daemon and "rls_sbx_0001" in daemon
    assert "--cap-drop" in daemon and "--security-opt" in daemon
    assert "-v" in daemon and "/work/agents:/agents:rw" in daemon
    assert daemon[-3:] == [d.image, "sleep", "infinity"]


def test_exec_targets_the_agents_subdir(project):
    d = DockerExecutor(_settings(project))
    # Each exec just sets the working dir to that agent's subdir in the shared
    # container — no new container per agent.
    ex = d.build_exec_argv("rls_sbx_0001", "agent_0007", ["python", ".runtime/x.py"])
    assert ex == ["docker", "exec", "-w", "/agents/agent_0007",
                  "-e", "HOME=/agents/agent_0007", "-e", "PYTHONPATH=/agents/agent_0007",
                  "-e", "PYTHONUNBUFFERED=1", "rls_sbx_0001", "python", ".runtime/x.py"]


def test_one_container_reused_across_agents(project, monkeypatch):
    # Two different agents under the same root must share ONE container.
    d = DockerExecutor(_settings(project))
    started = []
    monkeypatch.setattr(d, "build_daemon_argv", lambda root, name: started.append(name) or ["true"])
    monkeypatch.setattr("subprocess.run", lambda *a, **k: type("P", (), {"returncode": 0, "stdout": "", "stderr": ""})())
    monkeypatch.setattr(d, "_alive", lambda name: True)
    d._session_container(_settings(project).root / "workspace/agents/agent_0001")
    d._session_container(_settings(project).root / "workspace/agents/agent_0002")
    assert len(started) == 1  # only one container ever created


def test_reuse_flag_read_from_settings(project):
    assert DockerExecutor(_settings(project)).reuse is True


def test_executor_shutdown_is_safe(project):
    rt = make_runtime(project, client=None)  # uses SubprocessExecutor
    assert isinstance(rt.executor, SubprocessExecutor)
    rt.executor.shutdown()  # no-op, must not raise


def test_select_executor_disables_when_docker_required_and_missing(project, monkeypatch):
    from swarm import sandbox
    from swarm.sandbox import DisabledExecutor, SubprocessExecutor, select_executor
    monkeypatch.setattr(sandbox, "docker_available", lambda: False)
    s = _settings(project)  # SANDBOX_BACKEND=docker, SANDBOX_REQUIRE_DOCKER=true

    ex = select_executor(s)
    assert isinstance(ex, DisabledExecutor)
    # It refuses to run code instead of touching the host.
    res = ex.run_python("print(1)", "/tmp", 5)
    assert res.exit_code is None and "sandbox unavailable" in res.stderr

    # Opt-in to host execution only when explicitly allowed.
    sp = project / "settings" / "main.settings"
    sp.write_text(sp.read_text().replace("SANDBOX_REQUIRE_DOCKER=true",
                                         "SANDBOX_REQUIRE_DOCKER=false"))
    assert isinstance(select_executor(_settings(project)), SubprocessExecutor)


def test_model_warmup_loads_and_returns_name(project):
    from conftest import MockClient
    rt = make_runtime(project, MockClient(lambda *_: "ok"))
    name = rt.model.warmup("primary")
    assert name == "mock-model:latest"
