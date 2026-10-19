"""FR-MTG-11: the bot's voice is `SpeechProvider.synthesize` behind config/voice*.yaml, with the local voice as backup.
Offline: the dev config's fake voice and scripted providers; no network."""

import asyncio
from typing import Any

import pytest
from tilo_providers.errors import NotConfigured, QuotaError, RequestError
from tilo_providers.speech import FakeSpeechProvider

from bot import providers as P
from bot.tts import FallbackTTS, TTSError


def collect(tts, text="Hello there"):
    async def go():
        return [c async for c in tts.stream(text)]

    return asyncio.run(go())


def test_FR_MTG_11_the_dev_voice_is_the_deterministic_fake_with_the_configured_sample_rate():
    assert P.voice_file().name == "voice.dev.yaml"
    tts = P.ProviderTTS()
    assert tts.sample_rate == 24000 and tts.config.vendor == "fake"
    first, again = b"".join(collect(tts)), b"".join(collect(tts))
    assert first == again and len(first) > 0 and len(first) % 2 == 0
    assert b"".join(collect(tts, "A different sentence")) != first


def test_FR_MTG_11_the_live_switch_selects_the_real_voice_config_without_calling_it(monkeypatch):
    monkeypatch.setenv("LIVE", "1")  # selection only
    assert P.voice_file().name == "voice.yaml"
    monkeypatch.setenv("TILO_VOICE_FILE", "/elsewhere/voice.yaml")
    assert str(P.voice_file()).endswith("voice.yaml") and "elsewhere" in str(P.voice_file())


def test_FR_MTG_11_pcm_is_handed_on_in_player_sized_chunks_without_loss():
    class Pcm(FakeSpeechProvider):
        def synthesize(self, text: str, *, voice: str | None = None, **kwargs: Any) -> bytes:
            return bytes(range(256)) * 50  # 12800 bytes

    chunks = collect(P.ProviderTTS(Pcm()))
    assert b"".join(chunks) == bytes(range(256)) * 50 and all(len(c) <= 4800 for c in chunks)


def test_FR_MTG_11_text_is_collapsed_and_capped_before_the_provider_sees_it():
    seen: list[str] = []

    class Spy(FakeSpeechProvider):
        def synthesize(self, text: str, *, voice: str | None = None, **kwargs: Any) -> bytes:
            seen.append(text)
            return b"\x00\x01"

    tts = P.ProviderTTS(Spy())
    collect(tts, "a   b\n\nc " + "x" * 1000)
    assert seen[0].startswith("a b c x") and len(seen[0]) == tts.config.max_chars


@pytest.mark.parametrize(
    "error,permanent",
    [
        (NotConfigured("no live switch"), True),
        (RequestError("refused"), True),
        (QuotaError("429 secret"), False),
        (RuntimeError("boom"), False),
    ],
)
def test_FR_MTG_11_voice_failures_are_typed_tts_errors_with_no_provider_text(error, permanent):
    class Failing(FakeSpeechProvider):
        def synthesize(self, text: str, *, voice: str | None = None, **kwargs: Any) -> bytes:
            raise error

    with pytest.raises(TTSError) as exc:
        collect(P.ProviderTTS(Failing()))
    assert (
        exc.value.permanent is permanent and "secret" not in str(exc.value) and type(error).__name__ in str(exc.value)
    )


def test_FR_MTG_11_a_voice_that_cannot_speak_is_replaced_by_the_backup_for_the_meeting():
    class NoLive(FakeSpeechProvider):
        calls = 0

        def synthesize(self, text: str, *, voice: str | None = None, **kwargs: Any) -> bytes:
            NoLive.calls += 1
            raise NotConfigured("no live switch")

    class Backup:
        name, sample_rate = "backup", 22050

        async def stream(self, text):
            yield b"xx"

    f = FallbackTTS(P.ProviderTTS(NoLive()), Backup())
    assert collect(f) == [b"xx"] and collect(f) == [b"xx"] and NoLive.calls == 1  # not retried every reply
    assert f.name == "backup" and f.sample_rate == 22050


def test_FR_MTG_11_make_tts_builds_the_dev_fake_with_the_local_voice_as_backup_only_when_espeak_exists(monkeypatch):
    monkeypatch.setattr("bot.providers.LocalTTS", lambda: (_ for _ in ()).throw(TTSError("espeak-ng is not installed")))
    tts = P.make_tts()
    assert isinstance(tts, P.ProviderTTS)  # no backup available: the configured voice alone

    class Local:
        name, sample_rate = "local", 22050

    monkeypatch.setattr("bot.providers.LocalTTS", Local)
    assert isinstance(P.make_tts(), FallbackTTS)
