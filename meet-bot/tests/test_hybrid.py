import math
import struct

from bot.chatread import parse_chat_panel
from bot.hybrid import RATE, AudioBuffer, CaptionSpans, SpeechSegmenter, assign_speaker, to_wav


def tone(seconds, amp=8000):
    n = int(RATE * seconds)
    return struct.pack("<" + "h" * n, *[int(amp * math.sin(2 * math.pi * 300 * i / RATE)) for i in range(n)])


def silence(seconds):
    return bytes(int(RATE * seconds) * 2)


def run(seg, pcm, chunk=3200):
    out = []
    for i in range(0, len(pcm), chunk):
        out += seg.feed(pcm[i : i + chunk])
    return out + seg.flush()


def test_segmenter_finds_two_speech_bursts_and_ignores_silence_and_clicks():
    pcm = silence(3) + tone(2.0) + silence(1.5) + tone(0.2) + silence(1.5) + tone(1.5) + silence(2)
    segs = run(SpeechSegmenter(), pcm)
    assert len(segs) == 2  # the 0.2 s click is dropped
    (a1, b1), (a2, b2) = segs
    assert 2.6 <= a1 <= 3.1 and 4.9 <= b1 <= 5.5
    assert 7.9 <= a2 <= 8.4 and 9.2 <= b2 <= 10.0


def test_segmenter_cuts_long_monologues():
    segs = run(SpeechSegmenter(max_s=5.0), tone(13) + silence(1))
    assert len(segs) >= 3 and all(b - a <= 5.3 for a, b in segs)


def test_segmenter_streaming_matches_odd_chunk_sizes():
    pcm = silence(1) + tone(1.5) + silence(1.5)
    assert run(SpeechSegmenter(), pcm, chunk=1234) == run(SpeechSegmenter(), pcm, chunk=6400)


def test_audio_buffer_slices_by_stream_time_and_drops_old_audio():
    buf = AudioBuffer(keep_s=2.0)
    buf.append(silence(1) + tone(1))
    assert abs(buf.seconds - 2.0) < 1e-6 and len(buf.slice(1.0, 2.0)) == RATE * 2
    buf.append(tone(2))  # pushes the first second out
    assert buf.slice(0.0, 1.0) == b"" and len(buf.slice(2.0, 4.0)) == RATE * 4


def test_wav_wrapper_is_a_valid_wav():
    wav = to_wav(tone(0.5))
    assert wav[:4] == b"RIFF" and wav[8:12] == b"WAVE"


def test_speaker_assignment_uses_caption_timing_with_lag():
    spans = [("Alex", 10.0, 14.0), ("Priya", 16.5, 19.0)]
    assert assign_speaker((9.0, 12.5), spans) == ("Alex", [])
    assert assign_speaker((15.5, 18.0), spans)[0] == "Priya"
    assert assign_speaker((40.0, 42.0), spans) == (None, [])


def test_crosstalk_reports_the_other_active_speaker():
    spans = [("Alex", 10.0, 15.0), ("Priya", 11.0, 15.0)]
    best, others = assign_speaker((9.5, 13.5), spans)
    assert {best, *others} == {"Alex", "Priya"}


def test_caption_spans_merge_close_activity_and_split_long_gaps():
    s = CaptionSpans(gap_s=2.5)
    for t in (1.0, 2.0, 3.5, 10.0):
        s.touch("Alex", t)
    assert s.as_tuples() == [("Alex", 1.0, 3.5), ("Alex", 10.0, 10.0)]


CHAT = """In-call messages
Let participants send messages
Continuous chat is turned off
Messages will not be saved for meeting participants when the call ends.
1:50 PM
Hi, I'm an AI assistant taking notes for this meeting.
John Regi 1:52 PM
Tilo, what is the launch date?
See https://example.com/spec for details
Send a message
"""


def test_chat_panel_parser_separates_own_and_other_messages():
    assert parse_chat_panel(CHAT) == [
        ("You", "Hi, I'm an AI assistant taking notes for this meeting."),
        ("John Regi", "Tilo, what is the launch date? See https://example.com/spec for details"),
    ]
    assert parse_chat_panel("") == []
