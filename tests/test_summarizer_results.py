"""Summarize-on-overflow + the results library."""
from conftest import MockClient, make_runtime

from swarm.summarizer import SUMMARY_HEADER


def _settings_with(project, **overrides):
    sp = project / "settings" / "main.settings"
    text = sp.read_text(encoding="utf-8")
    for k, v in overrides.items():
        # naive replace of KEY=...
        import re
        text = re.sub(rf"(?m)^{k}=.*$", f"{k}={v}", text)
    sp.write_text(text, encoding="utf-8")


def test_summarizer_compresses_top_down(project):
    # Tiny context budget so the history overflows it (floors at ~4096 chars).
    _settings_with(project, DEFAULT_NUM_CTX="200", DEFAULT_NUM_PREDICT="50",
                   TOKEN_SAFETY_MARGIN="0", SUMMARIZE_RECENT_FRACTION="0.5")

    def script(last_user, system, n):
        if last_user.startswith("Summarize the earlier conversation"):
            return "BRIEFING: earlier work covered steps 1-3."
        return "noted"

    rt = make_runtime(project, MockClient(script))
    # Exceed the ~4096-char floor budget so overflow actually triggers.
    history = [{"role": "user", "content": f"old message number {i} " + "x" * 200}
               for i in range(40)]
    history.append({"role": "user", "content": "the latest and most important turn"})
    rt.model.summarizer.fit("coding", history)

    # Oldest turns were compressed into a single briefing at the top...
    assert history[0]["content"].startswith(SUMMARY_HEADER)
    assert "BRIEFING" in history[0]["content"]
    # ...and the latest turn is retained verbatim.
    assert history[-1]["content"] == "the latest and most important turn"
    assert len(history) < 41  # compressed from the original 41 messages


def test_no_summary_when_under_budget(project):
    rt = make_runtime(project, MockClient(lambda *_: "x"))
    history = [{"role": "user", "content": "small"} for _ in range(6)]
    before = list(history)
    rt.model.summarizer.fit("coding", history)
    assert history == before  # untouched


def test_save_result_writes_flat_file(project):
    rt = make_runtime(project, MockClient(lambda *_: "x"))
    path = rt.save_result("build a tool", "FINISHED OUTPUT\nthe code")
    assert path.exists()
    assert path.suffix == ".md"
    assert path.parent.name == "results"
    body = path.read_text(encoding="utf-8")
    assert "build a tool" in body and "the code" in body
