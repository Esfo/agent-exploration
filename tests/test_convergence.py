import json

from conftest import MockClient, make_runtime

from swarm import ids
from swarm.convergence import Member, run_convergence


def _script(last_user, system, n):
    lu = last_user
    if "Would you like to run any of your tools" in lu:      # CONVERGENCE_TEST
        return "No testing needed right now. EXIT"
    if "vote either FINISHED or INCOMPLETE" in lu:           # CONVENE + VOTE
        return "From my angle the work is complete.\nI vote FINISHED"
    if "Form either a plan or a prototype" in lu:            # INITIATION + ACTION
        return "Here is the work.\nFINISHED OUTPUT\nthe deliverable"
    return "ok"


def test_agent_reshapes_final_output_after_sandbox(project):
    state = {"action": 0}

    def script(lu, system, n):
        if "Would you like to run any of your tools" in lu:
            return "YES"
        if "write the code you would like to run" in lu:
            return "```python\nprint('hi')\n```\nEXIT"
        if "output of running your code" in lu:
            return "thanks, noted"
        if "Form either a plan or a prototype" in lu:
            state["action"] += 1
            tag = "revised after testing" if state["action"] > 1 else "initial output"
            return f"FINISHED OUTPUT\n{tag}"
        if "vote either FINISHED or INCOMPLETE" in lu:
            return "I vote FINISHED"
        return "ok"

    rt = make_runtime(project, MockClient(script))
    m = Member(id=ids.next_id("agent"), agent_type="coding", task="t", task_truncated="t")
    result = run_convergence(rt, [m], [], "goal", "council 1", max_rounds=2)
    # The final output reflects the post-sandbox reshape, not the first draft.
    out = dict(result.final_outputs())
    assert "revised after testing" in list(out.values())[0]


def test_unanimous_first_round_finishes(project):
    lines = []
    rt = make_runtime(project, MockClient(_script), sink=lines.append)
    members = [
        Member(id=ids.next_id("agent"), agent_type="coding", task="write code",
               task_truncated="write code"),
        Member(id=ids.next_id("agent"), agent_type="philosophizing", task="check intent",
               task_truncated="check intent"),
    ]
    result = run_convergence(rt, members, inherited=[], inherited_goal="ship it",
                             council_id="council_test")
    assert result.status == "FINISHED"
    assert result.rounds == 1
    assert not result.force_resolved
    outs = dict(result.final_outputs())
    assert all("the deliverable" in v for v in outs.values())

    # vote logged to jsonl + a YAY-NAY line printed
    votes_file = project / "logs" / "votes.jsonl"
    rec = json.loads(votes_file.read_text().splitlines()[0])
    assert rec["pattern"] == "2-0" and rec["status"] == "FINISHED"
    assert any("2-0 (YAY-NAY)" in ln for ln in lines)


def test_force_resolves_when_never_unanimous(project):
    def dissent(last_user, system, n):
        if "vote either FINISHED or INCOMPLETE" in last_user:
            return "Not there yet.\nI vote INCOMPLETE"
        if "WAIT" in last_user and "CONTINUE" in last_user:   # reinitiate
            return "I will keep going. CONTINUE"
        if "CONTINUE or SPAWN" in last_user or "CONTINUE, or SPAWN" in last_user:
            return "I can handle this. CONTINUE"
        if "Would you like to run any of your tools" in last_user:
            return "EXIT"
        return "working FINISHED OUTPUT\nstuff"
    rt = make_runtime(project, MockClient(dissent))
    members = [Member(id=ids.next_id("agent"), agent_type="coding", task="t",
                      task_truncated="t")]
    result = run_convergence(rt, members, [], "goal", "c1", max_rounds=3)
    assert result.status == "FINISHED"
    assert result.force_resolved
    assert result.rounds == 3
