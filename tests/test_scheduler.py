"""Resource monitor, scheduler slots, and parallel child execution."""
import threading
import time

from swarm import ids
from swarm.resources import ResourceMonitor, Snapshot
from swarm.scheduler import Scheduler
from swarm.settings import Settings
from tests.conftest import MockClient, make_runtime


def _settings(project):
    return Settings.load(project / "settings" / "main.settings")


# ---------- resource monitor ----------
def test_ram_percent_in_range():
    m = ResourceMonitor()
    r = m.ram_percent()
    assert 0.0 <= r <= 100.0


def test_disk_percent_in_range():
    m = ResourceMonitor(".")
    assert 0.0 <= m.disk_percent() <= 100.0


def test_under_pressure_uses_snapshot(project):
    s = _settings(project)
    m = ResourceMonitor()
    hi = Snapshot(ram_percent=99.0, cpu_percent=0, vram_percent=None, disk_percent=0)
    pressured, reason = m.under_pressure(s, hi)
    assert pressured and "RAM" in reason
    lo = Snapshot(ram_percent=1.0, cpu_percent=1.0, vram_percent=1.0, disk_percent=1.0)
    assert m.under_pressure(s, lo)[0] is False


# ---------- scheduler slots ----------
def test_inference_slot_limits_concurrency(project):
    s = _settings(project)
    s._v["MAX_ACTIVE_GPU_AGENTS"] = "1"  # force a single GPU slot for this test
    sched = Scheduler(s, ResourceMonitor())

    active = {"n": 0, "max": 0}
    lock = threading.Lock()

    def worker():
        with sched.inference_slot("gpu"):
            with lock:
                active["n"] += 1
                active["max"] = max(active["max"], active["n"])
            time.sleep(0.05)
            with lock:
                active["n"] -= 1

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert active["max"] == 1  # only one GPU inference at a time


# ---------- parallel children ----------
def test_parallel_children_all_complete(project):
    ids._counters.clear()

    def script(last_user, model, n):
        if "child agents finished" in last_user:
            return '<<tool:finish>>{"status":"complete","summary":"merged"}<</tool>>'
        if "ROLE: chat_agent" in last_user:
            return ('<<tool:spawn_agents>>{"children":['
                    '{"title":"a","task":"ta","role":"coding_agent"},'
                    '{"title":"b","task":"tb","role":"coding_agent"},'
                    '{"title":"c","task":"tc","role":"coding_agent"}]}<</tool>>')
        return '<<tool:finish>>{"status":"complete","summary":"leaf"}<</tool>>'

    ctx, runner = make_runtime(project, MockClient(script))
    ctx.scheduler = Scheduler(_settings(project), ResourceMonitor())
    sid = ids.next_id("swarm")
    ctx.db.create_swarm(sid, "fan out")
    root = ctx.create_root(sid, "chat_agent", "Root", "fan out work")
    result = runner.run_agent(root["id"])

    assert result["status"] == "complete"
    agents = ctx.db.list_swarm_agents(sid)
    children = [a for a in agents if a["parent_agent_id"] == root["id"]]
    assert len(children) == 3
    assert all(c["status"] == "complete" for c in children)
