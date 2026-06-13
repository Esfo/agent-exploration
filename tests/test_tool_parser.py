from swarm.tool_parser import parse, has_tool_block


def test_basic_block():
    text = '<<tool:finish>>\n{"status": "complete", "summary": "done"}\n<</tool>>'
    calls = parse(text)
    assert len(calls) == 1
    assert calls[0].name == "finish"
    assert calls[0].ok
    assert calls[0].args["status"] == "complete"


def test_markdown_fences_tolerated():
    text = '<<tool:report_progress>>\n```json\n{"message": "hi"}\n```\n<</tool>>'
    calls = parse(text)
    assert calls[0].ok
    assert calls[0].args["message"] == "hi"


def test_trailing_comma_tolerated():
    text = '<<tool:finish>>{"status": "complete", "summary": "x",}<</tool>>'
    calls = parse(text)
    assert calls[0].ok
    assert calls[0].args["summary"] == "x"


def test_missing_close_tag_recovered():
    text = 'thinking...\n<<tool:finish>>\n{"status": "complete"}'
    calls = parse(text)
    assert len(calls) == 1
    assert calls[0].ok


def test_two_blocks():
    text = ('<<tool:report_progress>>{"message":"a"}<</tool>>'
            '<<tool:finish>>{"status":"complete"}<</tool>>')
    calls = parse(text)
    assert [c.name for c in calls] == ["report_progress", "finish"]


def test_invalid_json_reports_error():
    text = '<<tool:finish>>{not json at all]<</tool>>'
    calls = parse(text)
    assert not calls[0].ok
    assert calls[0].error


def test_prose_around_json():
    text = 'Here you go: <<tool:finish>> some text {"status":"complete"} trailing <</tool>>'
    calls = parse(text)
    assert calls[0].ok
    assert calls[0].args["status"] == "complete"


def test_has_tool_block():
    assert has_tool_block("<<tool:x>>{}<</tool>>")
    assert not has_tool_block("no tools here")
