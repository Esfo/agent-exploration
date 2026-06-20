from swarm.live import Live


def test_live_streams_buffer_and_scrolls_notices(capsys):
    live = Live(height=2)
    live.enabled = True            # force on (capsys stdout isn't a TTY)
    live.log("council 1 convening")
    live.feed("hello ")
    live.feed("world")
    out = capsys.readouterr().out
    assert "council 1 convening" in out      # durable notice scrolled above
    assert "hello world" in out              # buffer shows accumulated stream
    assert "\x1b[" in out                    # ANSI control codes used


def test_live_disabled_is_plain(capsys):
    live = Live(enabled=False)
    live.log("just a line")
    live.feed("ignored")
    out = capsys.readouterr().out
    assert out.strip() == "just a line"
    assert "\x1b[" not in out
