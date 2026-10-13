"""FR-MTG-11 (M2): Gemini Live as an optional, flagged voice behind `config/voice.yaml` (PL-01, PL-02, PL-06, PL-07).
Chirp 3 HD stays the default; the flag is off in the shipped config. Tests use a fake session, hand-written recordings
and a fake SDK client only: no network, no SDK session, no live switch, no real audio."""

from __future__ import annotations

import asyncio
import base64
import dataclasses
import hashlib
import json
import logging
import pathlib
from contextlib import asynccontextmanager
from types import SimpleNamespace as NS
from typing import Any

import pytest
import yaml
from tilo_providers.config import ProviderConfigError
from tilo_providers.errors import NotConfigured, ProviderError, RequestError
from tilo_providers.gemini_live_voice_adapter import GeminiLiveVoiceProvider, LiveSessionSettings, recording_key
from tilo_providers.interfaces import SpeechProvider
from tilo_providers.voice import (
    GoogleVoiceProvider,
    LiveVoiceConfig,
    VoiceConfig,
    build_voice_provider,
    load_voice_config,
)

REPO = pathlib.Path(__file__).resolve().parents[3]
FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"
TEXT = "The release is Friday."
LIVE = LiveVoiceConfig(True, "gemini-live-voice", "gemini-3.8-live", "Leda", "global", 5.0, 128, False)
CONFIG = VoiceConfig(
    "google-cloud-tts",
    "chirp3-hd",
    "chirp-3-hd",
    "en-US-Chirp3-HD-Test",
    24000,
    400,
    4000,
    "asia-southeast1",
    7.0,
    LIVE,
)
A, B = bytes(range(100)), bytes(range(100, 200))  # the two chunks of the hand-written recording
FAKE_TOKEN = "ya" + "29." + "a0AfH6SMB" + "x" * 20  # assembled at runtime: no secret-looking literal in the repo


def with_live(**changes: Any) -> VoiceConfig:
    return dataclasses.replace(CONFIG, live=dataclasses.replace(LIVE, **changes))


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("LIVE", "TILO_RECORD", "K_SERVICE", "CLOUD_RUN_JOB", "GOOGLE_VERTEX_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(FIXTURES / "no-such-adc.json"))


def message(audio: bytes | None = A, *, complete: bool = False, mime: str = "audio/pcm;rate=24000", **extra: Any):
    parts = [] if audio is None else [NS(inline_data=NS(data=audio, mime_type=mime))]
    content = NS(model_turn=NS(parts=parts), turn_complete=complete, interrupted=extra.get("interrupted", False))
    return NS(server_content=content, usage_metadata=extra.get("usage"))


class Transport:
    """A fake Live session factory: records the settings and the user turn, replies with the given messages."""

    def __init__(self, replies: list[Any], error: Exception | None = None) -> None:
        self.replies, self.error = replies, error
        self.settings: list[LiveSessionSettings] = []
        self.sent: list[dict[str, Any]] = []
        self.opened = self.closed = 0

    def __call__(self, settings: LiveSessionSettings):
        self.settings.append(settings)
        return self.connect()

    @asynccontextmanager
    async def connect(self, *args: Any, **kwargs: Any):
        self.opened += 1
        try:
            yield self
        finally:
            self.closed += 1

    async def send_client_content(self, **kwargs: Any) -> None:
        self.sent.append(kwargs)

    async def receive(self):
        for reply in self.replies:
            yield reply
        if self.error is not None:
            raise self.error


def provider(transport: Any = None, config: VoiceConfig = CONFIG, **kwargs: Any) -> GeminiLiveVoiceProvider:
    return GeminiLiveVoiceProvider(config, fixtures_dir=FIXTURES, session_factory=transport, **kwargs)


GOOD = [message(A), message(B, complete=True)]


def write_voice_yaml(tmp_path: pathlib.Path, mutate: Any = None, *, enabled: bool = True) -> pathlib.Path:
    raw = yaml.safe_load((REPO / "config" / "voice.yaml").read_text(encoding="utf-8"))
    raw["voice"]["live"]["enabled"] = enabled
    if mutate is not None:
        mutate(raw["voice"])
    path = tmp_path / "voice.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return path


def test_FR_MTG_11_PL_01_shipped_config_has_the_flag_off_and_chirp_stays_the_default():
    real = load_voice_config(REPO / "config" / "voice.yaml", models_path=REPO / "config" / "models.yaml")
    assert real.vendor == "google-cloud-tts" and real.live is not None and real.live.enabled is False
    assert real.live.price_approved is False
    assert isinstance(build_voice_provider(real, fixtures_dir=FIXTURES), GoogleVoiceProvider)
    dev = load_voice_config(REPO / "config" / "voice.dev.yaml", models_path=REPO / "config" / "models.yaml")
    assert dev.live is None


def test_FR_MTG_11_PL_01_the_flag_alone_selects_the_live_adapter_and_it_is_a_speech_provider(tmp_path):
    flagged = load_voice_config(write_voice_yaml(tmp_path), models_path=REPO / "config" / "models.yaml")
    built = build_voice_provider(flagged, fixtures_dir=FIXTURES)
    assert isinstance(built, GeminiLiveVoiceProvider) and isinstance(built, SpeechProvider)
    assert flagged.sample_rate == 24000 and flagged.live is not None and flagged.live.enabled


@pytest.mark.parametrize(
    "mutate",
    [
        lambda v: v["live"].update(enabled="yes"),
        lambda v: v["live"].update(enabled=1),
        lambda v: v["live"].update(voice="has space"),
        lambda v: v["live"].update(model=""),
        lambda v: v["live"].update(timeout_s=0),
        lambda v: v["live"].update(timeout_s=61),
        lambda v: v["live"].update(max_output_tokens=0),
        lambda v: v["live"].update(price_approved="true"),
        lambda v: v["live"].update(location="not a region"),
        lambda v: v["live"].update(base_url="https://example.invalid"),
        lambda v: v.update(live="on"),
        lambda v: v.update(vendor="fake"),
        lambda v: v.update(sample_rate=16000),
    ],
)
def test_FR_MTG_11_PL_07_a_bad_live_section_fails_start_up_loudly(tmp_path, mutate):
    path = write_voice_yaml(tmp_path, mutate)
    with pytest.raises(ProviderConfigError):
        load_voice_config(path, models_path=REPO / "config" / "models.yaml")


def test_FR_MTG_11_PL_07_a_denylisted_live_model_id_is_refused(tmp_path):
    models = yaml.safe_load((REPO / "config" / "models.yaml").read_text(encoding="utf-8"))
    models["rules"]["deny"] = [*models["rules"]["deny"], "denied-live-*"]
    (tmp_path / "models.yaml").write_text(yaml.safe_dump(models), encoding="utf-8")
    path = write_voice_yaml(tmp_path, lambda v: v["live"].update(model="denied-live-model"), enabled=False)
    with pytest.raises(ProviderConfigError, match="PL-07"):
        load_voice_config(path)  # the flag is off: the id is still checked


def test_FR_MTG_11_PL_02_replay_serves_the_hand_written_recording_and_never_builds_a_client(monkeypatch):
    from google import genai

    monkeypatch.setattr(genai, "Client", lambda **kwargs: pytest.fail("replay opened an SDK client"))
    live = provider()
    assert list(live.synthesize_stream(TEXT)) == [A, B]
    assert live.synthesize(TEXT) == A + B
    assert live.last_timing is not None and live.last_timing.chunks == 2 and live.last_timing.audio_bytes == 200
    assert live.last_timing.characters == len(TEXT)


def test_FR_MTG_11_PL_02_replay_miss_is_not_configured_and_never_falls_through_to_live(monkeypatch):
    from google import genai

    monkeypatch.setattr(genai, "Client", lambda **kwargs: pytest.fail("a replay miss went live"))
    with pytest.raises(NotConfigured, match="no recording"):
        provider().synthesize_stream("A reply nobody recorded.")
    monkeypatch.setenv("LIVE", "1")  # the user's switch alone does not price the adapter
    with pytest.raises(NotConfigured, match="PL-06"):
        provider().synthesize_stream("A reply nobody recorded.")


def test_FR_MTG_11_PL_02_committed_recordings_are_synthetic_keyed_and_valid():
    files = sorted((FIXTURES / "voice-live-recordings").glob("*.json"))
    assert files
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["synthetic"] is True and data["v"] == "1.0"
        assert path.stem == data["key"] == recording_key(data["profile"], data["model"], data["voice"], TEXT)
        assert data["text_sha256"] == hashlib.sha256(TEXT.encode()).hexdigest()
        assert "text" not in data  # only the digest: a recording never stores what the bot said


@pytest.mark.parametrize(
    "edit",
    [
        lambda d: d.update(chunks_b64=[base64.b64encode(b"\x01").decode()]),  # odd length: not 16-bit samples
        lambda d: d.update(chunks_b64=[]),
        lambda d: d.update(chunks_b64=["not base64!"]),
        lambda d: d.update(key="0" * 16),
        lambda d: d.update(sample_rate=16000),
        lambda d: d.update(text_sha256="f" * 64),
        lambda d: d.update(chunks_b64=[base64.b64encode(bytes(5000)).decode()]),  # over max_audio_bytes (4000)
    ],
)
def test_FR_MTG_11_PL_02_an_invalid_recording_is_refused_not_played(tmp_path, edit):
    source = next((FIXTURES / "voice-live-recordings").glob("*.json"))
    data = json.loads(source.read_text(encoding="utf-8"))
    edit(data)
    folder = tmp_path / "voice-live-recordings"
    folder.mkdir()
    (folder / source.name).write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ProviderError):
        list(GeminiLiveVoiceProvider(CONFIG, fixtures_dir=tmp_path).synthesize_stream(TEXT))


def test_FR_MTG_11_PL_02_fake_session_gets_config_model_voice_prompt_and_the_text_as_data():
    transport = Transport(GOOD)
    assert provider(transport).synthesize(TEXT) == A + B
    assert transport.opened == transport.closed == 1
    (settings,) = transport.settings
    assert (settings.model, settings.voice, settings.max_output_tokens) == ("gemini-3.8-live", "Leda", 128)
    assert "aloud" in settings.system_instruction and TEXT not in settings.system_instruction
    assert transport.sent == [{"turns": {"role": "user", "parts": [{"text": TEXT}]}, "turn_complete": True}]


def test_FR_MTG_11_PL_02_voice_override_wins_and_an_odd_byte_carries_into_the_next_piece():
    transport = Transport([message(b"\x01\x02\x03"), message(b"\x04", complete=True)])
    assert list(provider(transport).synthesize_stream(TEXT, voice="Puck")) == [b"\x01\x02", b"\x03\x04"]
    assert transport.settings[0].voice == "Puck"


def test_FR_MTG_11_PL_02_bad_requests_are_refused_before_any_session_opens():
    transport = Transport(GOOD)
    live = provider(transport)
    for call in (
        lambda: live.synthesize_stream(""),
        lambda: live.synthesize_stream("x" * 401),
        lambda: live.synthesize_stream(TEXT, voice="../x"),
        lambda: live.synthesize_stream(TEXT, speed=2),
    ):
        with pytest.raises(RequestError):
            call()
    with pytest.raises(RequestError):
        live.transcribe(b"audio")
    assert transport.opened == 0


@pytest.mark.parametrize(
    ("replies", "match"),
    [
        ([message(A, complete=False)], "did not finish"),
        ([message(None, complete=True)], "no audio"),
        ([message(A, mime="audio/pcm;rate=16000", complete=True)], "format"),
        ([message(A, interrupted=True)], "interrupted"),
        ([message(bytes(5000), complete=True)], "cap"),
    ],
)
def test_FR_MTG_11_PL_02_a_broken_turn_is_a_provider_error_and_the_session_closes(replies, match):
    transport = Transport(replies)
    with pytest.raises(ProviderError, match=match):
        provider(transport).synthesize(TEXT)
    assert transport.closed == transport.opened == 1


def test_FR_MTG_11_PL_02_session_errors_carry_a_class_name_and_never_a_token():
    transport = Transport([message(A)], error=RuntimeError(f"Bearer {FAKE_TOKEN}"))
    with pytest.raises(ProviderError) as caught:
        provider(transport).synthesize(TEXT)
    assert FAKE_TOKEN not in str(caught.value) and "RuntimeError" in str(caught.value)
    assert caught.value.__cause__ is None and transport.closed == 1
    assert FAKE_TOKEN not in provider().redact(f"x {FAKE_TOKEN} y")


def test_FR_MTG_11_PL_02_a_stalled_session_times_out_and_cleans_up():
    stalled = Transport([])

    async def forever():
        await asyncio.Event().wait()
        yield message()

    stalled.receive = forever  # type: ignore[method-assign]
    with pytest.raises(ProviderError, match="timed out"):
        provider(stalled, with_live(timeout_s=0.05)).synthesize(TEXT)
    assert stalled.closed == stalled.opened == 1


def test_FR_MTG_11_PL_02_closing_the_stream_early_closes_the_session():
    transport = Transport(GOOD)
    pieces = provider(transport).synthesize_stream(TEXT)
    assert next(pieces) == A
    pieces.close()
    assert transport.closed == transport.opened == 1


def test_FR_MTG_11_PL_02_timing_hook_gets_counts_only_and_a_failing_hook_does_not_break_the_voice(caplog):
    seen: list[Any] = []

    def hook(timing: Any) -> None:
        seen.append(timing)
        raise RuntimeError("hook broke")

    caplog.set_level(logging.INFO, logger="tilo_providers.voice")
    assert provider(Transport(GOOD), on_timing=hook).synthesize(TEXT) == A + B
    assert [(t.characters, t.chunks, t.audio_bytes) for t in seen] == [(len(TEXT), 2, 200)]
    assert TEXT not in caplog.text and "Leda" not in caplog.text


def test_FR_MTG_11_PL_06_live_path_needs_the_price_flag_a_project_and_the_users_switch(monkeypatch):
    from google import genai

    monkeypatch.setattr(genai, "Client", lambda **kwargs: pytest.fail("built an SDK client without approval"))
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "tilo-dev-test")
    monkeypatch.setenv("LIVE", "1")
    with pytest.raises(NotConfigured, match="PL-06"):  # the quote is not approved
        GeminiLiveVoiceProvider(CONFIG, fixtures_dir=None).synthesize_stream(TEXT)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT")
    with pytest.raises(NotConfigured, match="GOOGLE_CLOUD_PROJECT"):  # approved, but no project
        GeminiLiveVoiceProvider(with_live(price_approved=True), fixtures_dir=None).synthesize_stream(TEXT)


def test_FR_MTG_11_PL_02_priced_live_path_opens_one_sdk_session_with_the_configured_model_and_voice(monkeypatch):
    from google import genai

    captured: dict[str, Any] = {}
    transport = Transport(GOOD)

    class Live:
        def connect(self, *, model: str, config: Any):
            captured.update(model=model, config=config)
            return transport.connect()

    class Client:
        def __init__(self, **kwargs: Any) -> None:
            captured["client"] = kwargs

            async def aclose() -> None:
                captured["closed"] = True

            self.aio = NS(live=Live(), aclose=aclose)

    monkeypatch.setattr(genai, "Client", Client)
    monkeypatch.setenv("LIVE", "1")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "tilo-dev-test")
    assert GeminiLiveVoiceProvider(with_live(price_approved=True), fixtures_dir=None).synthesize(TEXT) == A + B
    assert captured["client"]["vertexai"] is True and captured["client"]["project"] == "tilo-dev-test"
    assert captured["client"]["location"] == "global" and captured["model"] == "gemini-3.8-live"
    voice = captured["config"].speech_config.voice_config.prebuilt_voice_config.voice_name
    assert voice == "Leda" and captured["config"].max_output_tokens == 128 and captured["closed"] is True
