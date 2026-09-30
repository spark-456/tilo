import asyncio

import httpx
import pytest

from bot.speaker import NullSpeaker, VoiceSpeaker
from bot.tts import ElevenLabsTTS, TTSError

FAKE_KEY = "fake" + "-" + "key" + "-for-tests"


class FakeTTS:
    name, sample_rate = "fake", 16000

    def __init__(self, chunks=(b"aa", b"bb"), error=None):
        self.chunks, self.error = chunks, error

    async def stream(self, text):
        if self.error:
            raise self.error
        for c in self.chunks:
            yield c


class FakePlayer:
    def __init__(self, log, cut_after=None):
        self.log, self.cut_after, self.played = log, cut_after, []

    async def play(self, chunks, rate, should_stop):
        self.log.append("play-start")
        async for c in chunks:
            if should_stop():
                self.log.append("cut")
                return False
            self.played.append(c)
        self.log.append("play-end")
        return True


class FakeMic:
    def __init__(self, log, works=True):
        self.log, self.works = log, works

    async def set(self, on):
        self.log.append("mic-on" if on else "mic-off")
        return self.works


class Activity:
    def __init__(self, talking_polls=0, loud=0.0):
        self.polls, self.loud = talking_polls, loud

    def speaking_within(self, w):
        self.polls -= 1
        return self.polls >= 0

    def loud_run_s(self):
        return self.loud


def speaker(log, tts=None, activity=None, **kw):
    return VoiceSpeaker(tts or FakeTTS(), FakePlayer(log), FakeMic(log), activity, tail_s=0, **kw)


def test_speaks_unmuted_then_mutes_again():
    log = []
    res = asyncio.run(speaker(log).say("Hello there."))
    assert res.spoken and not res.interrupted and res.first_audio_s is not None
    assert log == ["mic-on", "play-start", "play-end", "mic-off"]


def test_waits_for_a_pause_before_speaking():
    log = []
    res = asyncio.run(speaker(log, activity=Activity(talking_polls=3)).say("Hi."))
    assert res.spoken and res.waited_s >= 0.2


def test_gives_up_if_people_never_stop_talking_and_leaves_the_mic_alone():
    log = []
    res = asyncio.run(speaker(log, activity=Activity(talking_polls=10**6), max_wait_s=0.3).say("Hi."))
    assert not res.spoken and "kept talking" in res.error and log == []


def test_barge_in_stops_speech_and_remutes():
    log = []
    res = asyncio.run(speaker(log, activity=Activity(loud=0.9)).say("A long answer."))
    assert res.spoken and res.interrupted and "cut" in log and log[-1] == "mic-off"


def test_voice_failure_never_raises_so_chat_can_be_the_backup():
    for tts in (FakeTTS(error=TTSError("ElevenLabs rejected the API key")), FakeTTS(chunks=())):
        log = []
        res = asyncio.run(speaker(log, tts=tts).say("Hi."))
        assert not res.spoken and res.error
        assert log[-1] == "mic-off"  # never leaves the microphone open


def test_unmute_failure_is_reported_not_spoken():
    log = []
    sp = VoiceSpeaker(FakeTTS(), FakePlayer(log), FakeMic(log, works=False), None, tail_s=0)
    res = asyncio.run(sp.say("Hi."))
    assert not res.spoken and "microphone" in res.error and "play-start" not in log


def test_null_speaker_is_chat_only():
    assert not asyncio.run(NullSpeaker().say("x")).spoken


# --- ElevenLabs client (mock HTTP transport, no network) -----------------------------------------------------------
def make_tts(handler):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return ElevenLabsTTS(api_key=FAKE_KEY, voice_id="voice123", model="eleven_flash_v2_5", client=client)


async def collect(tts, text="Hello"):
    return [c async for c in tts.stream(text)]


def test_elevenlabs_streams_pcm_and_sends_the_right_request():
    seen = {}

    def handler(request):
        seen["url"], seen["key"], seen["body"] = str(request.url), request.headers["xi-api-key"], request.read()
        return httpx.Response(200, content=b"\x01\x02" * 5000)

    chunks = asyncio.run(collect(make_tts(handler)))
    assert b"".join(chunks) == b"\x01\x02" * 5000
    assert "/v1/text-to-speech/voice123/stream" in seen["url"] and "output_format=pcm_24000" in seen["url"]
    assert seen["key"] == FAKE_KEY and b"eleven_flash_v2_5" in seen["body"] and FAKE_KEY.encode() not in seen["body"]


@pytest.mark.parametrize(
    "status,needle",
    [
        (401, "rejected the API key"),
        (403, "Text to Speech"),
        (402, "Text to Speech"),
        (429, "limit"),
        (422, "voice or model"),
    ],
)
def test_elevenlabs_errors_are_explained_and_never_leak_the_key(status, needle):
    tts = make_tts(lambda r: httpx.Response(status, json={"detail": "nope " + FAKE_KEY}))
    with pytest.raises(TTSError) as e:
        asyncio.run(collect(tts))
    assert needle in str(e.value) and FAKE_KEY not in str(e.value)


def test_missing_key_raises_a_clear_error(monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    with pytest.raises(TTSError, match="ELEVENLABS_API_KEY"):
        ElevenLabsTTS()


def test_intro_line_discloses_voice_and_audio_handling():
    from bot.chat import INTRO, intro_text

    assert intro_text(False, False) == INTRO
    t = intro_text(True, True, True)
    assert "transcribed by an AI service" in t and "recorded locally" in t and "out loud" in t
    assert t.startswith("Hi, I'm an AI assistant taking notes for this meeting")


def test_fallback_voice_takes_over_on_plan_errors_and_remembers_it():
    from bot.tts import FallbackTTS

    class Broken:
        name, sample_rate, calls = "primary", 24000, 0

        async def stream(self, text):
            Broken.calls += 1
            raise TTSError(
                "ElevenLabs refused text-to-speech: give the key 'Text to Speech: Access' or check your plan"
            )
            yield b""

    class Backup:
        name, sample_rate = "backup", 22050

        async def stream(self, text):
            yield b"xx"
            yield b"yy"

    async def go():
        f = FallbackTTS(Broken(), Backup())
        a = [c async for c in f.stream("hi")]
        rate_a = f.sample_rate
        b = [c async for c in f.stream("again")]
        return a, b, rate_a, f.name

    a, b, rate, name = asyncio.run(go())
    assert (
        a == [b"xx", b"yy"] == b and rate == 22050 and name == "backup" and Broken.calls == 1
    )  # not retried every reply


def test_fallback_uses_primary_when_it_works():
    from bot.tts import FallbackTTS

    f = FallbackTTS(FakeTTS(chunks=(b"P1", b"P2")), FakeTTS(chunks=(b"B",)))
    assert asyncio.run(collect(f)) == [b"P1", b"P2"]
