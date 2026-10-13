"""FR-MTG-11 (docs/prd-addendum-people-agents.md): the bot's voice goes through `SpeechProvider.synthesize`; the vendor
(`google`, or the dev `fake`), voice, sample rate and caps are config (`config/voice.yaml`); a model id appears only
there; the Google adapter is tested against a fake SDK client and refuses to build one without the live switch. No test
here opens a network connection."""

from __future__ import annotations

import pathlib
from types import SimpleNamespace
from typing import Any

import pytest
import yaml
from _fake_genai_sdk import FakeAPIError, FakeClient, FakeModelsAPI
from tilo_providers.config import ProviderConfigError
from tilo_providers.errors import NotConfigured, ProviderError, QuotaError, RequestError
from tilo_providers.interfaces import SpeechProvider
from tilo_providers.speech import FakeSpeechProvider, SpeechRecordReplayProvider
from tilo_providers.voice import VoiceConfig, build_voice_provider, load_voice_config

REPO = pathlib.Path(__file__).resolve().parents[3]
PCM = bytes(range(256)) * 20  # 5120 bytes: an even count of 16-bit samples


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("LIVE", "TILO_RECORD", "K_SERVICE", "CLOUD_RUN_JOB"):
        monkeypatch.delenv(name, raising=False)


def write_voice_yaml(tmp_path: pathlib.Path, **overrides: Any) -> pathlib.Path:
    voice = {
        "vendor": "google",
        "profile": "google-voice",
        "model": "voice-model-x",
        "voice": "Kore",
        "sample_rate": 24000,
        "max_chars": 400,
        "max_audio_bytes": 2_400_000,
    }
    voice.update(overrides)
    path = tmp_path / "voice.yaml"
    path.write_text(yaml.safe_dump({"voice": {k: v for k, v in voice.items() if v is not None}}), encoding="utf-8")
    return path


def test_FR_MTG_11_real_and_dev_voice_configs_load_and_name_google_or_fake():
    real = load_voice_config(REPO / "config" / "voice.yaml", models_path=REPO / "config" / "models.yaml")
    assert real.vendor in ("google-cloud-tts", "google") and real.model and real.voice and real.sample_rate == 24000
    dev = load_voice_config(REPO / "config" / "voice.dev.yaml", models_path=REPO / "config" / "models.yaml")
    assert dev.vendor == "fake" and 0 < dev.max_chars <= 2000 and dev.max_audio_bytes > 0


@pytest.mark.parametrize(
    "overrides",
    [
        {"vendor": "elevenlabs"},
        {"vendor": "ElevenLabs"},
        {"vendor": "openai"},
        {"vendor": ""},
        {"vendor": None},
        {"model": None},
        {"voice": None},
        {"voice": "has space"},
        {"voice": "../x"},
        {"sample_rate": 0},
        {"sample_rate": 12345},
        {"sample_rate": True},
        {"max_chars": 0},
        {"max_chars": "400"},
        {"max_audio_bytes": -1},
    ],
)
def test_FR_MTG_11_bad_voice_config_fails_startup_loudly(tmp_path, overrides):
    with pytest.raises(ProviderConfigError):
        load_voice_config(write_voice_yaml(tmp_path, **overrides), models_path=tmp_path / "none.yaml")


def test_FR_MTG_11_a_denylisted_voice_model_id_fails_startup(tmp_path):
    models = tmp_path / "models.yaml"
    models.write_text(yaml.safe_dump({"rules": {"deny": ["gemini-2.5-*", "*-preview*"]}}), encoding="utf-8")
    with pytest.raises(ProviderConfigError, match="denied"):
        load_voice_config(write_voice_yaml(tmp_path, model="some-tts-preview"), models_path=models)


def test_FR_MTG_11_the_base_interface_has_a_non_abstract_synthesize_that_raises_not_configured():
    class OnlyTranscribes(SpeechProvider):
        def transcribe(self, audio: bytes, **kwargs: Any) -> Any:
            return {"segments": []}

    assert "synthesize" not in SpeechProvider.__abstractmethods__
    with pytest.raises(NotConfigured):
        OnlyTranscribes().synthesize("hello")
    assert issubclass(NotConfigured, ProviderError)


def test_FR_MTG_11_the_fake_voice_is_deterministic_16_bit_mono_pcm_without_network():
    fake = FakeSpeechProvider()
    first, again = fake.synthesize("Hello there, team."), fake.synthesize("Hello there, team.")
    assert first == again and len(first) > 0 and len(first) % 2 == 0
    assert fake.synthesize("Something else entirely") != first
    assert fake.synthesize("Hello there, team.", voice="Other") != first  # the voice name is part of the sound
    assert len(fake.synthesize("a b c d e f g h")) > len(fake.synthesize("a"))  # longer text, longer audio


@pytest.mark.parametrize("text", ["", "   ", None, 5])
def test_FR_MTG_11_synthesize_needs_non_empty_text(text):
    with pytest.raises(RequestError):
        FakeSpeechProvider().synthesize(text)  # type: ignore[arg-type]


def test_FR_MTG_11_the_fake_voice_is_refused_when_live_or_deployed(monkeypatch):
    monkeypatch.setenv("K_SERVICE", "x")
    with pytest.raises(ProviderConfigError):
        FakeSpeechProvider()


def test_FR_MTG_11_the_factory_builds_fake_or_google_and_refuses_any_other_vendor(tmp_path):
    cfg = VoiceConfig("fake", "f", "fake-voice", "Fake", 24000, 400, 100_000)
    assert isinstance(build_voice_provider(cfg, fixtures_dir=tmp_path), FakeSpeechProvider)
    google = build_voice_provider(VoiceConfig("google", "g", "m", "Kore", 24000, 400, 100_000), fixtures_dir=tmp_path)
    assert isinstance(google, SpeechProvider) and not isinstance(google, SpeechRecordReplayProvider)
    for vendor in ("elevenlabs", "deepgram", "openai", "azure", "aws", "polly"):
        with pytest.raises(ProviderConfigError):
            build_voice_provider(VoiceConfig(vendor, "p", "m", "v", 24000, 400, 1), fixtures_dir=tmp_path)


def test_FR_MTG_11_the_google_voice_makes_no_call_and_builds_no_client_without_the_live_switch(tmp_path):
    google = build_voice_provider(VoiceConfig("google", "g", "m", "Kore", 24000, 400, 100_000), fixtures_dir=tmp_path)
    with pytest.raises(NotConfigured, match="LIVE"):
        google.synthesize("Hello")  # the socket guard would fail any real call


def test_FR_MTG_11_text_over_the_char_cap_is_refused_before_any_call(tmp_path):
    cfg = VoiceConfig("fake", "f", "fake-voice", "Fake", 24000, 10, 100_000)
    with pytest.raises(RequestError):
        build_voice_provider(cfg, fixtures_dir=tmp_path).synthesize("x" * 11)


# --- the Google adapter (Gemini speech output), against a fake SDK client only --------------------------------------


def google_provider(client: Any, **kwargs: Any):
    from tilo_providers.google_speech_adapter import GoogleSpeechProvider

    return GoogleSpeechProvider(
        model="speech-model-x",
        project="demo-project",
        location="global",
        client=client,
        tts_model="voice-model-x",
        tts_voice="Kore",
        **kwargs,
    )


def audio_response(pcm: Any) -> Any:
    part = SimpleNamespace(inline_data=SimpleNamespace(data=pcm, mime_type="audio/L16;codec=pcm;rate=24000"))
    return SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]))])


def client_for(result: Any = None, error: Exception | None = None) -> FakeClient:
    return FakeClient(FakeModelsAPI(generate_content_result=result, generate_content_error=error))


def test_FR_MTG_11_google_voice_refuses_to_build_a_client_without_live(fake_genai_sdk):
    from tilo_providers.google_speech_adapter import GoogleSpeechProvider

    with pytest.raises(ProviderError, match="LIVE=1"):
        GoogleSpeechProvider(model="m", project="demo-project", location="global", tts_model="t", tts_voice="Kore")


def test_FR_MTG_11_google_voice_asks_for_audio_with_the_configured_model_and_voice(fake_genai_sdk):
    client = client_for(audio_response(PCM))
    assert google_provider(client).synthesize("Hello there.") == PCM
    (call,) = client.models.calls
    assert call["model"] == "voice-model-x" and call["contents"] == "Hello there."
    config = call["config"]
    assert config["response_modalities"] == ["AUDIO"]
    assert config["speech_config"]["voice_config"]["prebuilt_voice_config"]["voice_name"] == "Kore"
    client = client_for(audio_response(PCM))
    google_provider(client).synthesize("Hi.", voice="Puck")  # a per-call voice wins over the configured one
    assert (
        client.models.calls[0]["config"]["speech_config"]["voice_config"]["prebuilt_voice_config"]["voice_name"]
        == "Puck"
    )


@pytest.mark.parametrize(
    "result",
    [
        None,
        SimpleNamespace(candidates=[]),
        SimpleNamespace(candidates=[SimpleNamespace(content=None)]),
        audio_response(b""),
        audio_response("text"),
        audio_response(b"\x01"),
    ],
)
def test_FR_MTG_11_google_voice_fails_closed_on_a_bad_reply(fake_genai_sdk, result):
    with pytest.raises(ProviderError):
        google_provider(client_for(result)).synthesize("Hello")


def test_FR_MTG_11_google_voice_maps_errors_and_never_echoes_a_token(fake_genai_sdk):
    with pytest.raises(QuotaError) as excinfo:
        google_provider(client_for(error=FakeAPIError(429, "quota ya29.SECRET-token-value"))).synthesize("Hello")
    assert "SECRET-token-value" not in str(excinfo.value)
    with pytest.raises(ProviderError):
        google_provider(client_for(error=ValueError("boom"))).synthesize("Hello")


def test_FR_MTG_11_google_voice_needs_a_tts_model_and_clean_arguments(fake_genai_sdk):
    from tilo_providers.google_speech_adapter import GoogleSpeechProvider

    transcribe_only = GoogleSpeechProvider(model="m", project="demo-project", location="global", client=client_for())
    with pytest.raises(NotConfigured):
        transcribe_only.synthesize("Hello")
    provider = google_provider(client_for(audio_response(PCM)))
    with pytest.raises(RequestError):
        provider.synthesize("Hello", voice="bad voice!")
    with pytest.raises(RequestError):
        provider.synthesize("Hello", speed=2)
    with pytest.raises(RequestError):
        provider.synthesize("")


def test_FR_MTG_11_the_returned_audio_is_capped_by_the_config_not_by_trust(tmp_path, fake_genai_sdk, monkeypatch):
    cfg = VoiceConfig("google", "g", "voice-model-x", "Kore", 24000, 400, 1000)
    google = build_voice_provider(cfg, fixtures_dir=tmp_path)
    monkeypatch.setenv("LIVE", "1")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "demo-project")
    google._live = google_provider(client_for(audio_response(PCM)))  # inject the live adapter; no client is built
    with pytest.raises(ProviderError, match="cap"):
        google.synthesize("Hello")
