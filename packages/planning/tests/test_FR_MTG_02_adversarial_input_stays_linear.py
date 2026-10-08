"""FR-MTG-02 hardening: transcript text is untrusted, so no input may make the parsers super-linear (ReDoS) or raise
anything but a refusal. Every case is a wall-clock bound measured with `time.perf_counter` (no sleeps): a pattern that
backtracks exponentially or quadratically blows far past it, a linear one is well under. The 26-dot `<v` line is the
review finding (it took 9.8 s); the long runs of spaces and the 4 MB single line cover the quadratic cases."""

from __future__ import annotations

import time

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from tilo_planning.recording import RecordingRejected, normalise_segments
from tilo_planning.transcript_ingest import MAX_INPUT_BYTES, TranscriptRejected, parse_transcript

BOUND_S = 3.0  # an exponential regression still blows far past this; headroom for a loaded machine
BIG_BOUND_S = (
    30.0  # a 4 MB single line is linear (seconds, even on a loaded laptop); a quadratic pattern would take hours
)
BIG_ATOMS = ["spaces", "dots", "voice_spaces", "lt", "ass_openers", "numeric_entity", "colon_spaces", "voice_dot_words"]
HEADER = {
    "vtt": b"WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n",
    "srt": b"1\n00:00:01,000 --> 00:00:02,000\n",
    "text": b"",
}
ATOMS = {
    "dots_after_voice": ("<v", "."),
    "voice_dot_words": ("<v.", "a."),
    "voice_spaces": ("<v", " "),
    "voice_tabs": ("<v", "\t"),
    "dots": ("", "."),
    "colons": ("", ":"),
    "colon_spaces": ("a", ": "),
    "spaces": ("", " "),
    "lt": ("", "<"),
    "voice_openers": ("", "<v"),
    "tag_openers": ("", "<a"),
    "digit_tag_openers": ("", "<1"),
    "ass_openers": ("", "{\\"),
    "ass_braces": ("{\\", "{"),
    "digits": ("", "1"),
    "numeric_entity": ("&#", "1"),
    "hex_entity": ("&#x", "f"),
    "time_like": ("", "1:"),
    "arrows": ("", "-->"),
}


def _run(kind: str, line: str) -> float:
    data = HEADER[kind] + line.encode("utf-8")
    assert len(data) <= MAX_INPUT_BYTES
    started = time.perf_counter()
    try:
        parsed = parse_transcript(kind, data)
        normalise_segments(parsed.segments, meeting_id="mt_adversarial", what="transcript")
    except (TranscriptRejected, RecordingRejected):
        pass  # a refusal is a fine answer; only a crash or a slow answer is not
    return time.perf_counter() - started


def _line(name: str, size: int) -> str:
    prefix, unit = ATOMS[name]
    return prefix + unit * (size // len(unit)) + "x"


@pytest.mark.parametrize("kind", ["vtt", "srt", "text"])
def test_FR_MTG_02_the_26_dot_voice_tag_from_the_review_is_fast(kind):
    assert _run(kind, "<v" + "." * 26 + "x") < BOUND_S
    assert _run(kind, "<v" + "." * 25_000 + "x") < BOUND_S


@pytest.mark.parametrize("kind", ["vtt", "srt", "text"])
@pytest.mark.parametrize("name", sorted(ATOMS))
def test_FR_MTG_02_long_adversarial_runs_parse_in_linear_time(kind, name):
    assert _run(kind, _line(name, 50_000)) < BOUND_S


@pytest.mark.parametrize("kind", ["vtt", "srt", "text"])
@pytest.mark.parametrize("name", BIG_ATOMS)
def test_FR_MTG_02_a_4_mb_single_line_is_bounded_for_every_format(kind, name):
    assert _run(kind, _line(name, MAX_INPUT_BYTES - 100)) < BIG_BOUND_S


@pytest.mark.parametrize("kind", ["vtt", "srt"])
def test_FR_MTG_02_adversarial_cue_lines_and_settings_are_linear(kind):
    sep = "." if kind == "vtt" else ","
    hostile = [
        " " * 50_000 + f"00:00:01{sep}000 --> 00:00:02{sep}000",
        f"00:00:01{sep}000" + " " * 50_000 + "-->" + " " * 50_000 + f"00:00:02{sep}000",
        f"00:00:01{sep}000 --> 00:00:02{sep}000 " + "<v" * 25_000,
        "1:" * 25_000 + f"00:00:01{sep}000 --> x",
        "9" * 50_000 + f":00:01{sep}000 --> 00:00:02{sep}000",
    ]
    for text in hostile:
        data = (b"WEBVTT\n\n" if kind == "vtt" else b"") + text.encode() + b"\nhello\n"
        started = time.perf_counter()
        try:
            parse_transcript(kind, data)
        except TranscriptRejected:
            pass
        assert time.perf_counter() - started < BOUND_S


@pytest.mark.parametrize("kind", ["vtt", "srt", "text"])
def test_FR_MTG_02_an_entity_with_thousands_of_digits_is_inert_text_not_a_crash(kind):
    data = HEADER[kind] + ("A &#" + "1" * 5000 + "; B &#x" + "f" * 5000 + "; C").encode()
    parsed = parse_transcript(kind, data)  # html.unescape would raise ValueError on a >4300 digit decimal entity
    content = normalise_segments(parsed.segments, meeting_id="mt_adversarial", what="transcript")
    text = content["utterances"][0]["text"]
    assert text.startswith("A ")
    if kind != "text":  # plain text keeps entities verbatim (and is cut at the per-line cap); only cues are decoded
        assert text.endswith(" C") and "\N{REPLACEMENT CHARACTER}" in text


@pytest.mark.parametrize("kind", ["vtt", "srt", "text"])
@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large])
@given(
    parts=st.lists(
        st.tuples(
            st.sampled_from(sorted({p + u for p, u in ATOMS.values()} | {"<v.a", " ", "\t"})), st.integers(1, 1_000)
        ),
        min_size=1,
        max_size=8,
    )
)
def test_FR_MTG_02_fuzz_parse_time_stays_bounded_for_repeated_hostile_pieces(kind, parts):
    line = "".join(piece * n for piece, n in parts)
    assert _run(kind, line) < BOUND_S
