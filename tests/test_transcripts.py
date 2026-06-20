"""Each agent's behind-the-scenes conversation is written to /workspace."""
from conftest import MockClient, make_runtime

from swarm import ids
from swarm.convergence import Member, run_convergence


def _script(last_user, system, n):
    if "Would you like to run any of your tools" in last_user:
        return "EXIT"
    if "vote either FINISHED or INCOMPLETE" in last_user:
        return "ok\nI vote FINISHED"
    if "Form either a plan or a prototype" in last_user:
        return "FINISHED OUTPUT\nthe work"
    return "ok"


def test_member_conversation_is_written(project):
    rt = make_runtime(project, MockClient(_script))
    m = Member(ids.next_id("agent"), "coding", "build it", "build it")
    run_convergence(rt, [m], [{"role": "user", "content": "context"}], "ship it", "c1",
                    max_rounds=2)

    convo = project / "workspace" / "agents" / m.id / "conversation.md"
    assert convo.exists()
    text = convo.read_text(encoding="utf-8")
    # Header + the actual turns (system/user/assistant) are recorded.
    assert f"coding ({m.id})" in text
    assert "## assistant" in text and "I vote FINISHED" in text
    assert "Form either a plan" in text  # the council deliberation is captured


def test_transcripts_can_be_disabled(project):
    sp = project / "settings" / "main.settings"
    sp.write_text(sp.read_text().replace("WRITE_TRANSCRIPTS=true", "WRITE_TRANSCRIPTS=false"))
    rt = make_runtime(project, MockClient(_script))
    m = Member(ids.next_id("agent"), "coding", "build it", "build it")
    run_convergence(rt, [m], [], "ship it", "c2", max_rounds=2)
    assert not (project / "workspace" / "agents" / m.id / "conversation.md").exists()
