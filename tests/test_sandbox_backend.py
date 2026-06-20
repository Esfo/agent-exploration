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


def test_persistent_daemon_and_exec_argv(project):
    d = DockerExecutor(_settings(project))
    daemon = d.build_daemon_argv("/tmp/agent", "rls_sbx_0001")
    # detached, auto-removed, named, hardened, kept alive with sleep infinity
    assert daemon[:4] == ["docker", "run", "-d", "--rm"]
    assert "--name" in daemon and "rls_sbx_0001" in daemon
    assert "--cap-drop" in daemon and "--security-opt" in daemon
    assert daemon[-3:] == [d.image, "sleep", "infinity"]

    # exec reuses the warm container (no hardening flags re-specified)
    ex = d.build_exec_argv("rls_sbx_0001", ["python", "/agent/.runtime/x.py"])
    assert ex == ["docker", "exec", "-w", "/agent", "rls_sbx_0001",
                  "python", "/agent/.runtime/x.py"]


def test_reuse_flag_read_from_settings(project):
    assert DockerExecutor(_settings(project)).reuse is True


def test_executor_shutdown_is_safe(project):
    rt = make_runtime(project, client=None)  # uses SubprocessExecutor
    assert isinstance(rt.executor, SubprocessExecutor)
    rt.executor.shutdown()  # no-op, must not raise
