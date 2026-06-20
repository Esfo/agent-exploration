from swarm.voting import parse_vote, tally_votes


def test_parse_vote_final_word_wins():
    assert parse_vote("I think... I vote FINISHED") == "finished"
    assert parse_vote("maybe I vote FINISHED but actually I vote INCOMPLETE") == "incomplete"
    assert parse_vote("no clear vote here") is None


def test_tally_and_pattern():
    t = tally_votes(["finished", "finished", "incomplete"])
    assert t.pattern == "2-1"
    assert t.status == "INCOMPLETE"
    assert not t.unanimous_finished

    t2 = tally_votes(["finished", "finished"])
    assert t2.pattern == "2-0"
    assert t2.status == "FINISHED"
    assert t2.unanimous_finished

    # unparsed votes count as NAY
    t3 = tally_votes(["finished", None])
    assert t3.pattern == "1-1"
