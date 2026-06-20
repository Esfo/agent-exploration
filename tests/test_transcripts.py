"""The recursive log tree: per-agent conversation files + a per-council votes log."""
from conftest import MockClient, make_runtime

from swarm.council import parse_directives, run_council


def _script(last_user, system, n):
    if "Would you like to run any of your tools" in last_user:
        return "EXIT"
    if "vote either FINISHED or INCOMPLETE" in last_user:
        return "ok\nI vote FINISHED"
    if "Form either a plan or a prototype" in last_user:
        return "FINISHED OUTPUT\nthe work"
    if "finalizing the work of a council" in last_user:
        return "RETAIN coding"
    if "Is this the final response" in last_user:
        return "CONFIRM"
    return "ok"


def test_council_tree_written(project, tmp_path):
    rt = make_runtime(project, MockClient(_script))
    members = parse_directives(rt, "coding: build it: Build it.\n\nphilosophizing: check: Check it.")
    council_dir = tmp_path / "primary" / "councils" / "council1"
    run_council(rt, members, [{"role": "user", "content": "context"}], "ship it", council_dir, "1")

    # Each agent has its own conversation file named by its unique id.
    files = {p.name for p in council_dir.iterdir()}
    coding_id = next(m.id for m in members if m.agent_type == "coding")
    assert f"coding_{coding_id}.txt" in files
    convo = (council_dir / f"coding_{coding_id}.txt").read_text(encoding="utf-8")
    assert "## assistant" in convo and "I vote FINISHED" in convo

    # The votes log records each round and who voted what — only votes.
    votes = (council_dir / "votes.txt").read_text(encoding="utf-8")
    assert "round 1" in votes
    assert f"coding_{coding_id}: FINISHED" in votes
    assert "tally" in votes and "YAY-NAY" in votes

    # The zipper has its own file too (one per council, no number).
    assert "zipper.txt" in files


def test_transcripts_can_be_disabled(project, tmp_path):
    sp = project / "settings" / "main.settings"
    sp.write_text(sp.read_text().replace("WRITE_TRANSCRIPTS=true", "WRITE_TRANSCRIPTS=false"))
    rt = make_runtime(project, MockClient(_script))
    members = parse_directives(rt, "coding: build it: Build it.")
    council_dir = tmp_path / "primary" / "councils" / "council1"
    run_council(rt, members, [], "ship it", council_dir, "1")
    # No transcript or votes files written.
    txt = [p for p in council_dir.glob("*.txt")] if council_dir.exists() else []
    assert txt == []
