"""Live display: one updating line per agent; compact one-liners."""
import io

from swarm.live_display import LiveDisplay
from swarm.progress import EventBus, _one_sentence


class FakeTTY(io.StringIO):
    def isatty(self):
        return True


def test_one_sentence_summary():
    assert _one_sentence("Implement add(). Then test it.") == "Implement add()."
    long = "x" * 100
    assert _one_sentence(long).endswith("…")
    assert "DONE CONDITION" not in _one_sentence("do the thing\nDONE CONDITION: it works")


def test_live_display_updates_in_place():
    s = FakeTTY()
    d = LiveDisplay(enabled=True, stream=s)
    assert d.enabled
    d.update("a1", "a1 running")
    d.update("a1", "a1 progress 50%")   # same agent updates in place
    d.update("a2", "a2 running")
    out = s.getvalue()
    # cursor-up ANSI used to repaint the region (in-place, not just appended)
    assert "\033[" in out
    assert d.rendered == 2  # two active agents in the region


def test_live_display_finish_scrolls_and_removes():
    s = FakeTTY()
    d = LiveDisplay(enabled=True, stream=s)
    d.update("a1", "a1 running")
    d.update("a2", "a2 running")
    d.finish("a1", "✓ a1 complete")
    assert "a1" not in d.active        # removed from the live region
    assert "a2" in d.active
    assert d.rendered == 1


def test_live_display_noop_without_tty():
    s = io.StringIO()  # no isatty()->True
    d = LiveDisplay(enabled=True, stream=s)
    assert not d.enabled
    d.update("a1", "x")
    assert s.getvalue() == ""


def test_eventbus_compact_lines_without_live(tmp_path):
    out = []
    bus = EventBus(tmp_path, sink=out.append, show={"CHAT_SHOW_AGENT_START": True,
                                                    "CHAT_SHOW_AGENT_FINISH": True}, live=False)
    bus.agent_started({"id": "agent_0005", "role": "reviewer",
                       "task": "verify the code matches the goal. extra stuff."})
    bus.agent_finished("agent_0005", {"status": "complete", "completion_percentage": 100,
                                      "note": "looks good"})
    # one line each, not multi-line blocks
    assert len(out) == 2
    assert all("\n" not in line for line in out)
    assert "agent_0005" in out[0] and "reviewer" in out[0]
    assert "verify the code matches the goal" in out[0]
    assert out[1].startswith("✓")
