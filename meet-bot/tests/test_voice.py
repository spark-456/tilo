import asyncio

from bot.speaker import NullSpeaker, VoiceSpeaker
from bot.tts import TTSError


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
    for tts in (
        FakeTTS(error=TTSError("the voice service rejected the credentials", permanent=True)),
        FakeTTS(chunks=()),
    ):
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
            raise TTSError("the voice service refused text-to-speech for this plan", permanent=True)
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


async def collect(tts, text="Hello"):
    return [c async for c in tts.stream(text)]


def test_fallback_uses_primary_when_it_works():
    from bot.tts import FallbackTTS

    f = FallbackTTS(FakeTTS(chunks=(b"P1", b"P2")), FakeTTS(chunks=(b"B",)))
    assert asyncio.run(collect(f)) == [b"P1", b"P2"]
