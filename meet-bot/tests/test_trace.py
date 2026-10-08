"""VA-04: the turn trace, the report, two-channel audio and the audit. Synthetic data only, no network."""

import asyncio
import json
import math
import struct
import time
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_ui import FakeBrowser, FakeSpeaker, session  # noqa: F401  (fixture reused)

from bot.audio_out import MIC_SINK, WavTap
from bot.clock import FakeClock
from bot.hybrid import RATE, LiveRecorder, parec_command
from bot.llm_fast import FastLLM
from bot.main import main
from bot.report import audit, render_report
from bot.trace import MARKS, TurnTrace, load_turns, percentile

FAKE_KEY = "k-" + "t4ce" * 6


def run(coro):
    return asyncio.run(coro)


# -- percentiles and the trace ---------------------------------------------------------------------------------------
def test_VA_04_percentiles_are_exact():
    data = [float(i) for i in range(1, 11)]
    assert percentile(data, 50) == 5.5 and percentile(data, 90) == pytest.approx(9.1)
    assert percentile([2.0], 90) == 2.0 and percentile([], 50) is None
    assert percentile([3.0, 1.0, 2.0], 50) == 2.0  # order does not matter


def test_VA_04_marks_are_written_relative_to_the_end_of_the_human_turn(tmp_path):
    clock = FakeClock(100.0)
    trace = TurnTrace(tmp_path / "turns.jsonl", clock, audio_start=40.0)
    turn = trace.new_turn(asker="John", text="When does the beta ship?", speech_end=110.0, speech_end_source="audio")
    turn.mark("addressed", 108.79)
    turn.mark("confirmed_end", 110.45)
    clock.t = 111.11
    turn.mark("first_sample")
    turn.route = "model"
    trace.finish(turn, "spoken")
    (row,) = load_turns(tmp_path / "turns.jsonl")
    assert row["marks"] == {"addressed": -1.21, "confirmed_end": 0.45, "first_sample": 1.11}
    assert row["route"] == "model" and row["outcome"] == "spoken" and row["asker"] == "John"
    assert row["speech_end_s"] == 70.0 and row["speech_end_source"] == "audio"  # on the audio clock
    with pytest.raises(ValueError):
        turn.mark("first_smaple")  # a typo must not silently create a mark
    assert "first_sample" in MARKS and "barge_stop" in MARKS and "chat_posted" in MARKS


# -- the report ------------------------------------------------------------------------------------------------------
def write_turns(run, rows):
    (run / "turns.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def turn_row(i, first_sample, route="model", **extra):
    marks = {
        "addressed": -1.21,
        "confirmed_end": 0.45,
        "llm_request": 0.46,
        "llm_first_token": 0.46 + 0.4 + i / 100,
        "tts_request": 0.9,
        "tts_first_pcm": 0.9 + 0.3,
        "first_sample": first_sample,
        "chat_posted": first_sample + 0.5,
    }
    return {
        "v": 1,
        "turn": i,
        "route": route,
        "outcome": "spoken",
        "asker": "John",
        "text": f"question {i}",
        "speech_end_s": 10.0 * i,
        "marks": marks,
        **extra,
    }


def test_VA_04_the_report_prints_the_waterfall_and_exact_p50_p90(tmp_path):
    firsts = [round(1.0 + 0.1 * i, 2) for i in range(10)]  # 1.0 .. 1.9
    write_turns(tmp_path, [turn_row(i + 1, f) for i, f in enumerate(firsts)])
    (tmp_path / "connections.jsonl").write_text(
        json.dumps({"kind": "attempt", "attempt": 1, "outcome": "timeout"})
        + "\n"
        + json.dumps({"kind": "attempt", "attempt": 2, "outcome": "ok"})
        + "\n",
        encoding="utf-8",
    )
    text = render_report(tmp_path)
    assert 'turn 1  route=model  outcome=spoken  asked_by=John  "question 1"' in text
    assert "first_sample     1.00   (budget 1.30)" in text
    assert "confirmed_end    0.45" in text and "addressed       -1.21" in text
    summary = text.strip().splitlines()[-1]
    assert summary.startswith("summary  n=10")
    assert "first_sample p50 1.45 p90 1.81" in summary  # linear interpolation between the closest ranks
    assert "tts_ttfb p50 0.30" in summary and "retries 1" in summary


def test_VA_04_instant_turns_are_judged_against_the_instant_budget(tmp_path):
    write_turns(tmp_path, [turn_row(1, 0.7, route="instant")])
    assert "(budget 0.80)" in render_report(tmp_path)


def test_VA_04_the_report_survives_missing_marks_and_empty_runs(tmp_path):
    assert "no turns" in render_report(tmp_path).lower()
    row = turn_row(1, 1.2)
    row["marks"] = {"confirmed_end": 0.45}  # a turn that was cancelled before any audio
    row["outcome"] = "cancelled"
    write_turns(tmp_path, [row])
    text = render_report(tmp_path)
    assert "outcome=cancelled" in text and "n=1" in text


# -- two-channel audio and the audit -----------------------------------------------------------------------------------
def write_wav(path, length_s, tones, amp=6000, noise=0):
    """Mono 16 kHz WAV: silence plus 440 Hz tones at (start_s, end_s) spans, optional low constant noise."""
    n = int(length_s * RATE)
    samples = [noise if i % 2 else -noise for i in range(n)]
    for a, b in tones:
        for i in range(int(a * RATE), min(n, int(b * RATE))):
            samples[i] = int(amp * math.sin(2 * math.pi * 440 * i / RATE))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(struct.pack("<" + "h" * n, *samples))


def test_VA_04_the_audit_measures_speech_end_to_first_bot_sample_within_20ms(tmp_path):
    write_wav(tmp_path / "audio.wav", 9, [(0.5, 2.0), (4.0, 5.0)])  # two questions
    write_wav(tmp_path / "bot.wav", 9, [(3.3, 3.8), (6.2, 6.9)])  # two answers
    rows = audit(tmp_path)
    gaps = [r["audio_s"] for r in rows]
    assert len(gaps) == 2
    assert gaps[0] == pytest.approx(1.3, abs=0.02) and gaps[1] == pytest.approx(1.2, abs=0.02)


def test_VA_04_the_audit_applies_the_start_offset_between_the_two_recordings(tmp_path):
    write_wav(tmp_path / "audio.wav", 6, [(0.5, 2.0)])
    write_wav(tmp_path / "bot.wav", 6, [(3.3, 3.8)])
    (tmp_path / "audio_clock.json").write_text(
        json.dumps({"audio_start": 100.0, "bot_start": 100.08}), encoding="utf-8"
    )
    (row,) = audit(tmp_path)
    assert row["audio_s"] == pytest.approx(1.38, abs=0.02)  # the bot file began 80 ms after the meeting file


def test_VA_04_low_noise_is_not_a_bot_sample(tmp_path):
    write_wav(tmp_path / "audio.wav", 4, [(0.5, 2.0)])
    write_wav(tmp_path / "bot.wav", 4, [], noise=40)
    assert audit(tmp_path) == []


def test_VA_04_the_audit_checks_the_logged_first_sample_against_the_audio(tmp_path):
    write_wav(tmp_path / "audio.wav", 9, [(0.5, 2.0)])
    write_wav(tmp_path / "bot.wav", 9, [(3.3, 3.8)])
    row = turn_row(1, 1.25)
    row["speech_end_s"] = 2.0  # anchored on the audio clock
    write_turns(tmp_path, [row])
    (result,) = audit(tmp_path)
    assert result["turn"] == 1 and result["logged_s"] == 1.25
    assert result["audio_s"] == pytest.approx(1.3, abs=0.02) and result["delta_s"] == pytest.approx(0.05, abs=0.02)
    assert "audit 1.30" in render_report(tmp_path)


def test_VA_04_report_and_audit_are_cli_commands(tmp_path, capsys):
    row = turn_row(1, 1.2)
    row["speech_end_s"] = 2.0
    write_turns(tmp_path, [row])
    write_wav(tmp_path / "audio.wav", 4, [(0.5, 2.0)])
    write_wav(tmp_path / "bot.wav", 4, [(3.2, 3.6)])
    assert main(["report", str(tmp_path)]) == 0 and "summary  n=1" in capsys.readouterr().out
    assert main(["audit", str(tmp_path)]) == 0 and "1.2" in capsys.readouterr().out
    assert main(["report", str(tmp_path / "missing")]) == 1


def test_VA_04_capture_uses_a_20ms_buffer_and_the_bot_tap_reads_the_mic_sink():
    assert "--latency-msec=20" in parec_command("tilo_out.monitor")
    tap = WavTap(Path("bot.wav"))  # nothing is opened until .open()
    assert f"--device={MIC_SINK}.monitor" in tap.command() and "--latency-msec=20" in tap.command()
    rec = LiveRecorder(None, SimpleNamespace(), SimpleNamespace(), lambda a, b: None)
    assert "--latency-msec=20" in rec.command()


def test_VA_04_the_bot_tap_writes_a_valid_wav(tmp_path):
    tap = WavTap(tmp_path / "bot.wav")
    tap.open()
    tap.write(struct.pack("<" + "h" * 1600, *([1000] * 1600)))
    tap.close()
    with wave.open(str(tmp_path / "bot.wav"), "rb") as w:
        assert (w.getframerate(), w.getnchannels(), w.getnframes()) == (RATE, 1, 1600)


# -- the model client and the session write the marks ------------------------------------------------------------------
class OkClient:
    def __init__(self):
        self.aio = SimpleNamespace(models=self)

    async def generate_content_stream(self, *, model, contents, config):
        async def chunks():
            await asyncio.sleep(0.05)
            yield SimpleNamespace(text="Hi.")

        return chunks()


def test_VA_04_the_fast_client_keeps_the_request_and_first_token_times():
    clock = FakeClock(10.0)
    llm = FastLLM("m", client_factory=OkClient, clock=clock.now)

    async def go():
        await llm.generate("s", "p")

    run(go())
    assert llm.last_call["request_at"] == 10.0 and llm.last_call["first_token_at"] == 10.0  # the fake clock never moved


def test_VA_04_connection_events_go_to_connections_jsonl(session, monkeypatch):  # noqa: F811
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    fast = session._build_fast()
    fast.on_attempt({"purpose": "fast", "attempt": 1, "outcome": "timeout", "code": None})
    rows = [json.loads(x) for x in (session.out_dir / "connections.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows[0]["kind"] == "attempt" and rows[0]["outcome"] == "timeout"
    assert FAKE_KEY not in json.dumps(rows)


def test_VA_04_a_spoken_reply_becomes_a_turn_with_marks(session):  # noqa: F811
    s = session
    s.br = FakeBrowser([[]])
    s.speaker = FakeSpeaker(speak_s=0.4, first_s=0.1)
    msg = SimpleNamespace(kind="direct_reply", text="Kickoff is in progress.", subject="q", t=5.0)

    async def go():
        now = s.clock.now()
        turn = s.trace.new_turn(asker="Sam", text="What is next?", speech_end=now - 0.5, speech_end_source="audio")
        turn.route = "model"
        fut = asyncio.get_running_loop().create_future()
        fut.set_result((msg, 0.3, {"question": "What is next?", "detected": now, "first_seen": now - 1, "turn": turn}))
        s.brain.last_quick_source = "model"
        await s._finish_quick(fut)
        t = time.monotonic()
        while not (s.out_dir / "turns.jsonl").exists() and time.monotonic() - t < 3:
            await asyncio.sleep(0.05)

    run(go())
    (row,) = load_turns(s.out_dir / "turns.jsonl")
    assert row["outcome"] == "spoken" and row["route"] == "model"
    for mark in ("tts_request", "tts_first_pcm", "first_sample", "playback_end", "chat_posted"):
        assert mark in row["marks"], mark
    assert row["marks"]["first_sample"] <= row["marks"]["chat_posted"]  # the chat copy never precedes the first sound
