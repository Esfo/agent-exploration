"""Convergence process: response->vote rounds until unanimous 'I vote FINISHED'."""
from swarm import ids
from swarm.convergence import parse_vote, run_convergence, FINISHED, INCOMPLETE
from tests.conftest import MockClient, make_runtime


def _is_vote(last_user: str) -> bool:
    return "would you vote" in last_user.lower()


def _group(ctx, sid, roles):
    root = ctx.create_root(sid, "chat_agent", "Root", "build a thing")
    return [ctx.create_child(parent=root, title=r, task=f"{r} angle", role=r,
                             done_condition="", suggested_model=None, priority=1)
            for r in roles]


# ----- parse_vote unit -----

def test_parse_vote_basic():
    assert parse_vote("blah blah\nI vote FINISHED") == FINISHED
    assert parse_vote("reasons... I vote INCOMPLETE") == INCOMPLETE
    assert parse_vote("i VoTe finished") == FINISHED
    assert parse_vote("no verdict here") is None


def test_parse_vote_last_wins():
    # Against instruction an agent mentions both; the final word governs.
    assert parse_vote("I vote INCOMPLETE earlier, but really I vote FINISHED") == FINISHED


# ----- full loop -----

def test_unanimous_finished_first_round(project):
    ids._counters.clear()

    def script(last_user, model, n):
        if _is_vote(last_user):
            return "My assessment is solid.\nI vote FINISHED"
        return "Here is my plan: do the work."

    ctx, _ = make_runtime(project, MockClient(script))
    sid = ids.next_id("swarm")
    ctx.db.create_swarm(sid, "g")
    agents = _group(ctx, sid, ["coding_agent", "testing_agent"])

    res = run_convergence(ctx, agents, inherited=[], goal_type="code")
    assert res.finished is True
    assert res.round_count == 1
    assert all(v.vote == FINISHED for v in res.rounds[0].votes)


def test_incomplete_then_converges(project):
    ids._counters.clear()
    counters = {"vote": 0}

    def script(last_user, model, n):
        if _is_vote(last_user):
            counters["vote"] += 1
            # second vote in round 1 dissents; everyone agrees thereafter.
            if counters["vote"] == 2:
                return "Not there yet.\nI vote INCOMPLETE"
            return "Good enough now.\nI vote FINISHED"
        return "plan/execute response"

    ctx, _ = make_runtime(project, MockClient(script))
    sid = ids.next_id("swarm")
    ctx.db.create_swarm(sid, "g")
    agents = _group(ctx, sid, ["coding_agent", "testing_agent"])

    res = run_convergence(ctx, agents, inherited=[], goal_type="code")
    assert res.finished is True
    assert res.round_count == 2
    assert res.rounds[0].unanimous_finished is False
    assert res.rounds[1].unanimous_finished is True


def test_never_converges_hits_round_cap(project):
    ids._counters.clear()
    sp = project / "settings" / "main.settings"
    sp.write_text(sp.read_text().replace("CONVERGENCE_MAX_ROUNDS=4", "CONVERGENCE_MAX_ROUNDS=2"))

    def script(last_user, model, n):
        if _is_vote(last_user):
            return "Still not done.\nI vote INCOMPLETE"
        return "more work needed"

    ctx, _ = make_runtime(project, MockClient(script))
    sid = ids.next_id("swarm")
    ctx.db.create_swarm(sid, "g")
    agents = _group(ctx, sid, ["coding_agent", "testing_agent"])

    res = run_convergence(ctx, agents, inherited=[], goal_type="code")
    assert res.finished is False
    assert res.round_count == 2


def test_votes_logged_to_jsonl(project):
    ids._counters.clear()

    def script(last_user, model, n):
        return "I vote FINISHED" if _is_vote(last_user) else "plan"

    ctx, _ = make_runtime(project, MockClient(script))
    sid = ids.next_id("swarm")
    ctx.db.create_swarm(sid, "g")
    agents = _group(ctx, sid, ["coding_agent", "testing_agent"])
    run_convergence(ctx, agents, inherited=[], goal_type="code")

    log = project / "logs" / "convergence.jsonl"
    assert log.exists()
    assert '"vote": "finished"' in log.read_text()


def test_convergence_runs_in_spawn_path(project):
    # Enable convergence (the test fixture disables it by default).
    sp = project / "settings" / "main.settings"
    sp.write_text(sp.read_text().replace("CONVERGENCE_ENABLED=false", "CONVERGENCE_ENABLED=true"))
    ids._counters.clear()

    def script(last_user, model, n):
        if "ROLE: chat_agent" in last_user:
            return ('<<tool:spawn_agents>>{"children":['
                    '{"title":"impl","task":"implement","role":"coding_agent"},'
                    '{"title":"verify","task":"verify","role":"testing_agent"}]}<</tool>>')
        if "child agents finished" in last_user:
            return '<<tool:finish>>{"status":"complete","summary":"done"}<</tool>>'
        if _is_vote(last_user):
            return "Looks solid.\nI vote FINISHED"
        if "either plan or execute" in last_user.lower():
            return "my plan/execute response"
        # each spawned child's own working turn
        return '<<tool:finish>>{"status":"complete","summary":"child did work"}<</tool>>'

    ctx, runner = make_runtime(project, MockClient(script))
    sid = ids.next_id("swarm")
    ctx.db.create_swarm(sid, "build a thing")
    root = ctx.create_root(sid, "chat_agent", "Root", "build a thing")
    res = runner.run_agent(root["id"])

    assert res["status"] == "complete"
    # convergence ran as part of the spawn path and logged a unanimous round.
    log = project / "logs" / "convergence.jsonl"
    assert log.exists()
    assert '"vote": "finished"' in log.read_text()


def _enable_program_voting(project):
    sp = project / "settings" / "main.settings"
    sp.write_text(sp.read_text().replace(
        "INSTRUCTION_PROGRAM_VOTING=false", "INSTRUCTION_PROGRAM_VOTING=true"))


def test_program_driven_voting_finishes(project):
    _enable_program_voting(project)
    ids._counters.clear()

    def script(last_user, model, n):
        # The instruction-program asks VERIFY questions with this suffix.
        if "Answer with a short YES or NO" in last_user:
            return "YES, the work is complete"
        return "my plan/execute response"

    ctx, _ = make_runtime(project, MockClient(script))
    sid = ids.next_id("swarm")
    ctx.db.create_swarm(sid, "g")
    agents = _group(ctx, sid, ["coding_agent", "testing_agent"])

    res = run_convergence(ctx, agents, inherited=[], goal_type="code")
    assert res.finished is True
    assert all(v.vote == FINISHED for v in res.rounds[0].votes)
    # the vote came from executing the agent's VERIFY program
    assert any("program vote" in v.reasoning for v in res.rounds[0].votes)


def test_program_driven_voting_incomplete(project):
    _enable_program_voting(project)
    ids._counters.clear()

    def script(last_user, model, n):
        if "Answer with a short YES or NO" in last_user:
            return "NO, not yet"
        return "more work needed"

    ctx, _ = make_runtime(project, MockClient(script))
    sid = ids.next_id("swarm")
    ctx.db.create_swarm(sid, "g")
    agents = _group(ctx, sid, ["coding_agent", "testing_agent"])

    res = run_convergence(ctx, agents, inherited=[], goal_type="code", max_rounds=1)
    assert res.finished is False
    assert all(v.vote == INCOMPLETE for v in res.rounds[0].votes)
