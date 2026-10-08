"""live-probe (experiment X4) against a fake Gemini Live server: protocol shape, timing, saved answers, key safety."""

import asyncio
import base64
import json
import math
import struct
import wave

import websockets

from bot import live_probe as lp

FAKE_KEY = "fake" + "-" + "live" + "-key"
REPLY_DELAY_S = 0.08


def tone(seconds: float, rate: int = 16000) -> bytes:
    n = int(seconds * rate)
    return struct.pack("<" + "h" * n, *[int(6000 * math.sin(i / 5)) for i in range(n)])


def fake_server(seen: dict, refuse_model: str | None = None):
    async def handler(ws):
        seen["headers"] = dict(ws.request.headers)
        in_turn = False
        async for raw in ws:
            m = json.loads(raw)
            if "setup" in m:
                seen["setup"] = m["setup"]
                if refuse_model and m["setup"]["model"].endswith(refuse_model):
                    await ws.close(1007, "Invalid resource field value")
                    return
                await ws.send(json.dumps({"setupComplete": {}}).encode())  # the real server sends JSON as bytes
            elif "clientContent" in m:
                seen["card"] = m["clientContent"]
            elif "realtimeInput" in m:
                ri = m["realtimeInput"]
                if "activityStart" in ri:
                    in_turn = True
                elif "audio" in ri:
                    seen["audio_outside_turn"] = seen.get("audio_outside_turn", False) or not in_turn
                    seen["mime"] = ri["audio"]["mimeType"]
                elif "activityEnd" in ri:
                    in_turn = False
                    await asyncio.sleep(REPLY_DELAY_S)
                    await ws.send(
                        json.dumps({"serverContent": {"inputTranscription": {"text": "what is on the agenda"}}})
                    )
                    audio = base64.b64encode(tone(0.3, 24000)).decode()
                    part = {"inlineData": {"mimeType": "audio/pcm;rate=24000", "data": audio}}
                    await ws.send(json.dumps({"serverContent": {"modelTurn": {"parts": [part]}}}))
                    await ws.send(json.dumps({"serverContent": {"outputTranscription": {"text": "Four items."}}}))
                    await ws.send(json.dumps({"serverContent": {"turnComplete": True}}))

    return handler


def run_probe(tmp_path, models, refuse_model=None, burst=True):
    seen: dict = {}

    async def scenario():
        async with websockets.serve(fake_server(seen, refuse_model), "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            qs = [
                lp.Question("What is on the agenda?", tone(0.5), 16000),
                lp.Question("Who owns it?", tone(0.4), 16000),
            ]
            return await lp.probe(
                models,
                qs,
                tmp_path,
                FAKE_KEY,
                "Agenda: 1. Kickoff",
                burst=burst,
                idle_s=0,
                url=f"ws://127.0.0.1:{port}/ws",
            )

    return asyncio.run(scenario()), seen


def test_X4_probe_uses_manual_turns_and_times_first_audio_after_activity_end(tmp_path, capsys):
    results, seen = run_probe(tmp_path, ["gemini-test-live"])
    setup = seen["setup"]
    assert setup["model"] == "models/gemini-test-live"
    assert setup["realtimeInputConfig"]["automaticActivityDetection"]["disabled"] is True
    assert setup["generationConfig"]["responseModalities"] == ["AUDIO"] and "outputAudioTranscription" in setup
    assert seen["card"]["turnComplete"] is False and "Kickoff" in json.dumps(seen["card"])
    assert seen["audio_outside_turn"] is False and seen["mime"] == "audio/pcm;rate=16000"
    assert seen["headers"]["x-goog-api-key"] == FAKE_KEY
    assert len(results) == 2
    for r in results:
        assert REPLY_DELAY_S * 0.8 <= r.first_audio_s < REPLY_DELAY_S + 0.5
        assert r.answer == "Four items." and r.heard_as == "what is on the agenda" and r.error is None
        assert abs(r.audio_s - 0.3) < 0.01 and r.done_s >= r.first_audio_s
    with wave.open(str(tmp_path / "gemini-test-live-01.wav"), "rb") as w:
        assert w.getframerate() == 24000 and w.getnframes() == int(0.3 * 24000)
    rows = [json.loads(x) for x in (tmp_path / "results.jsonl").read_text().splitlines()]
    assert len(rows) == 2 and "pcm" not in rows[0]
    assert FAKE_KEY not in capsys.readouterr().out


def test_X4_real_time_sending_paces_audio_like_a_live_speaker(tmp_path):
    import time

    t0 = time.monotonic()
    results, _ = run_probe(tmp_path, ["gemini-test-live"], burst=False)
    assert time.monotonic() - t0 >= 0.85  # 0.5 s + 0.4 s of question audio, sent at real-time speed
    assert all(r.first_audio_s is not None and r.first_audio_s < 0.6 for r in results)


def test_X4_a_refused_model_is_reported_and_the_next_model_still_runs(tmp_path, capsys):
    results, _ = run_probe(tmp_path, ["gemini-bad-live", "gemini-good-live"], refuse_model="gemini-bad-live")
    bad = [r for r in results if r.model == "gemini-bad-live"]
    good = [r for r in results if r.model == "gemini-good-live"]
    assert len(bad) == 1 and bad[0].index == -1 and "Invalid resource field value" in bad[0].error
    assert len(good) == 2 and all(r.first_audio_s is not None for r in good)
    summary = lp.summarize(results)
    assert "gemini-bad-live: no usable answers" in summary and "gemini-good-live: n=2" in summary
    assert FAKE_KEY not in capsys.readouterr().out + summary


def test_X4_summary_verdict_uses_our_side_of_the_latency_budget():
    fast = [lp.TurnResult("m-fast", i, "q", first_audio_s=0.6, pcm=b"\0\0") for i in range(5)]
    slow = [lp.TurnResult("m-slow", i, "q", first_audio_s=1.6, pcm=b"\0\0") for i in range(5)]
    silent = [lp.TurnResult("m-fast", 5, "q")]
    s = lp.summarize(fast + silent + slow)
    # early activityEnd at 0.25 s + 0.6 s + player 0.04 + Meet 0.25 = 1.14 s heard -> PASS; 1.6 s -> 2.14 s -> FAIL
    assert "m-fast: n=6 answered=5 silent=1" in s and "p50 1.14" in s and "-> PASS" in s.split("m-slow")[0]
    assert "m-slow" in s and s.rstrip().endswith("p90 <= 2.0)") and "-> FAIL" in s.split("m-slow")[1]


def test_X4_questions_come_from_recorded_phrases_ending_in_a_question_mark(tmp_path):
    rate = 16000
    with wave.open(str(tmp_path / "audio.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(tone(10.0))
    rows = [
        {"kind": "segment", "start_s": 1.0, "end_s": 2.0, "text": "What is on the agenda?"},
        {"kind": "segment", "start_s": 3.0, "end_s": 4.0, "text": "Good morning."},
        {"kind": "utterance", "text": "Ignored?"},
    ]
    (tmp_path / "latency.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    qs = lp.run_questions(tmp_path)
    assert [q.text for q in qs] == ["What is on the agenda?"]
    assert qs[0].rate == rate and len(qs[0].pcm) == int(1.3 * rate) * 2  # 1 s phrase + 150 ms margin each side
