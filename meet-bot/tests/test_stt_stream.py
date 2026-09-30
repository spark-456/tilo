import asyncio
import json
import math
import struct

import pytest
import websockets

from bot.stt_stream import AudioGate, ScribeStream, SpeakerNames, STTUnavailable, final_from_message

FAKE_KEY = "fake" + "-" + "key" + "-for-tests"
FRAME = 3200  # bytes in 100 ms


def loud():
    return struct.pack("<" + "h" * 1600, *[int(8000 * math.sin(i / 3)) for i in range(1600)])


def quiet():
    return bytes(FRAME)


def test_final_from_message_uses_word_times_and_majority_speaker():
    msg = {
        "message_type": "committed_transcript_with_timestamps",
        "text": " What is on the agenda? ",
        "words": [
            {"text": "What", "start": 1.0, "end": 1.2, "type": "word", "speaker_id": "speaker_0"},
            {"text": " ", "start": 1.2, "end": 1.25, "type": "spacing"},
            {"text": "agenda?", "start": 2.0, "end": 2.6, "type": "word", "speaker_id": "speaker_0"},
        ],
    }
    fin = final_from_message(msg, base_s=100.0)
    assert (fin.text, fin.start_s, fin.end_s, fin.speaker_id) == ("What is on the agenda?", 101.0, 102.6, "speaker_0")
    assert final_from_message({"text": "  "}) is None


def test_speaker_names_learn_from_captions_by_vote():
    n = SpeakerNames()
    assert n.resolve("speaker_0", "Alex") == "Alex"
    assert n.resolve("speaker_0", "Priya") == "Alex"
    assert n.resolve("speaker_0", None) == "Alex" and n.resolve("speaker_1", None) is None


def test_missing_key_is_a_clear_error(monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    with pytest.raises(STTUnavailable, match="ELEVENLABS_API_KEY"):
        ScribeStream(lambda t: None, lambda f: None)


# --- credit safety: the gate ----------------------------------------------------------------------------------------
def test_gate_sends_nothing_for_silence():
    g = AudioGate()
    assert all(g.feed(quiet(), i * 0.1) == [] for i in range(500))  # 50 s of silence: zero frames out


def test_gate_opens_with_lead_in_and_closes_after_a_short_tail():
    g = AudioGate(preroll_frames=3, hangover_frames=4)
    for i in range(10):
        g.feed(quiet(), i * 0.1)
    out = g.feed(loud(), 1.0)
    assert [round(t, 1) for _, t in out] == [0.7, 0.8, 0.9, 1.0]  # 3 frames of lead-in + the loud one
    tail = [g.feed(quiet(), 1.1 + i * 0.1) for i in range(8)]
    assert [len(x) for x in tail] == [1, 1, 1, 1, 0, 0, 0, 0]  # 4 frames of tail, then closed again
    assert g.feed(loud(), 2.0)[-1][1] == 2.0


def test_gate_reset_forgets_old_audio():
    g = AudioGate(preroll_frames=3)
    for i in range(5):
        g.feed(quiet(), i * 0.1)
    g.reset()
    assert len(g.feed(loud(), 1.0)) == 1


# --- protocol against a fake server -----------------------------------------------------------------------------------
def test_stream_against_a_fake_server_sends_audio_and_receives_partials_and_finals():
    seen = {"headers": None, "path": None, "chunks": 0, "sample_rates": set()}

    async def handler(ws):
        seen["headers"], seen["path"] = dict(ws.request.headers), ws.request.path
        async for raw in ws:
            m = json.loads(raw)
            if m["message_type"] == "input_audio_chunk" and m.get("audio_base_64"):
                seen["chunks"] += 1
                seen["sample_rates"].add(m.get("sample_rate"))
                if seen["chunks"] == 2:
                    await ws.send(json.dumps({"message_type": "partial_transcript", "text": "what is on"}))
                if seen["chunks"] == 3:
                    words = [{"text": "What", "start": 0.0, "end": 0.3, "type": "word", "speaker_id": "speaker_0"}]
                    await ws.send(
                        json.dumps({"message_type": "committed_transcript", "text": "What is on the agenda?"})
                    )
                    await ws.send(
                        json.dumps(
                            {
                                "message_type": "committed_transcript_with_timestamps",
                                "text": "What is on the agenda?",
                                "words": words,
                            }
                        )
                    )

    async def scenario():
        partials, finals = [], []
        async with websockets.serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            stream = ScribeStream(
                partials.append, finals.append, api_key=FAKE_KEY, url=f"ws://127.0.0.1:{port}/rt", keyterms=["Tilo"]
            )
            q = asyncio.Queue()
            task = asyncio.create_task(stream.run(q))
            for i in range(4):
                q.put_nowait((b"\x00\x01" * 1600, 50.0 + i * 0.1))
                await asyncio.sleep(0.05)
            await asyncio.sleep(0.3)
            q.put_nowait(None)
            await asyncio.wait_for(task, timeout=6)
        return partials, finals, stream

    partials, finals, stream = asyncio.run(scenario())
    assert seen["headers"]["xi-api-key"] == FAKE_KEY and "commit_strategy=vad" in seen["path"]
    assert "keyterms=Tilo" in seen["path"] and "pcm_16000" in seen["path"] and seen["sample_rates"] == {16000}
    assert partials == ["what is on"]
    assert len(finals) == 1 and finals[0].text == "What is on the agenda?" and finals[0].speaker_id == "speaker_0"
    assert finals[0].start_s == 50.0  # stream time 0 maps to the session time the audio started at
    assert abs(stream.total_sent_s - 0.4) < 1e-6 and stream.connections == 1


def test_no_audio_means_no_connection_and_quiet_closes_it_then_new_speech_reconnects():
    opened = []

    async def handler(ws):
        opened.append(1)
        async for _ in ws:
            pass

    async def scenario():
        async with websockets.serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            stream = ScribeStream(
                lambda t: None, lambda f: None, api_key=FAKE_KEY, url=f"ws://127.0.0.1:{port}/rt", idle_close_s=0.4
            )
            q = asyncio.Queue()
            task = asyncio.create_task(stream.run(q))
            await asyncio.sleep(0.6)
            assert opened == [] and stream.total_sent_s == 0  # silence: no connection at all
            q.put_nowait((b"\x00\x01" * 1600, 1.0))
            await asyncio.sleep(0.2)
            assert len(opened) == 1
            await asyncio.sleep(0.8)  # goes quiet: connection closes by itself
            q.put_nowait((b"\x00\x01" * 1600, 9.0))
            await asyncio.sleep(0.3)
            assert len(opened) == 2
            q.put_nowait(None)
            await asyncio.wait_for(task, timeout=6)
            return stream

    stream = asyncio.run(scenario())
    assert stream.connections == 2 and abs(stream.total_sent_s - 0.2) < 1e-6  # only the two 100 ms chunks were billed


def test_word_times_after_a_skipped_silence_map_back_to_session_time():
    async def handler(ws):
        n = 0
        async for raw in ws:
            n += 1
            if n == 3:  # the third chunk is the one that came after the gap
                await ws.send(
                    json.dumps(
                        {
                            "message_type": "committed_transcript_with_timestamps",
                            "text": "hello",
                            "words": [{"text": "hello", "start": 0.2, "end": 0.3, "type": "word"}],
                        }
                    )
                )

    async def scenario():
        finals = []
        async with websockets.serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            stream = ScribeStream(lambda t: None, finals.append, api_key=FAKE_KEY, url=f"ws://127.0.0.1:{port}/rt")
            q = asyncio.Queue()
            task = asyncio.create_task(stream.run(q))
            for t in (10.0, 10.1, 30.0):  # silence between 10.2 and 30.0 was never sent
                q.put_nowait((b"\x00\x01" * 1600, t))
            await asyncio.sleep(0.4)
            q.put_nowait(None)
            await asyncio.wait_for(task, timeout=6)
        return finals

    finals = asyncio.run(scenario())
    assert (
        len(finals) == 1 and abs(finals[0].start_s - 30.0) < 1e-6
    )  # stream 0.2 s == 0.2 s into the third chunk's span


def test_fatal_errors_stop_the_stream_and_never_leak_the_key(caplog):
    async def handler(ws):
        await ws.recv()
        await ws.send(json.dumps({"message_type": "auth_error", "error": "invalid key " + FAKE_KEY}))
        await asyncio.sleep(1)

    async def scenario():
        async with websockets.serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            stream = ScribeStream(lambda t: None, lambda f: None, api_key=FAKE_KEY, url=f"ws://127.0.0.1:{port}/rt")
            q = asyncio.Queue()
            q.put_nowait((b"\x00\x00" * 1600, 0.0))
            with pytest.raises(STTUnavailable) as e:
                await asyncio.wait_for(stream.run(q), timeout=6)
            assert FAKE_KEY not in str(e.value)

    with caplog.at_level("INFO"):
        asyncio.run(scenario())
    assert FAKE_KEY not in caplog.text
