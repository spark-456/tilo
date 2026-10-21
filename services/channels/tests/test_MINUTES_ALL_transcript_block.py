"""MINUTES-ALL: the transcript a minutes email may carry is plain text built by code, after the checked minutes."""

from tilo_channels.meeting_followup import TRANSCRIPT_CAP, _transcript_block


def test_MINUTES_ALL_lines_are_timed_named_and_labelled_as_not_checked():
    block = _transcript_block(
        [
            {"speaker": "Alex", "text": "What is the capital of France?", "t_ms": 65_400},
            {"speaker": "Tilo", "text": "Paris.", "t_ms": 70_000},
            {"speaker": None, "text": "Thanks", "t_ms": "x"},
        ]
    )
    assert block.startswith("\n\nTranscript, as Tilo captured it in the meeting (not checked):\n\n")
    assert block.endswith("[1:05] Alex: What is the capital of France?\n[1:10] Tilo: Paris.\n[0:00] Someone: Thanks")


def test_MINUTES_ALL_a_line_cannot_forge_a_header_or_a_second_line():
    block = _transcript_block([{"speaker": "Eve\nBcc: x@evil.example", "text": "a\r\nTo: y@evil.example", "t_ms": 0}])
    body = block.split("(not checked):\n\n", 1)[1]
    assert "\n" not in body and "\r" not in body


def test_MINUTES_ALL_a_long_transcript_is_cut_and_says_where_the_rest_is():
    lines = [{"speaker": "Alex", "text": "word " * 100, "t_ms": i * 1000} for i in range(200)]
    block = _transcript_block(lines)
    assert len(block) < TRANSCRIPT_CAP + 400
    assert block.endswith("(The transcript is cut here; the full transcript is in Tilo.)")


def test_MINUTES_ALL_no_lines_is_no_block():
    assert _transcript_block([]) == "" and _transcript_block([{"speaker": "A"}]) == ""
