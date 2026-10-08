"""FR-MTG-17 / FR-MTG-11 (docs/prd-addendum-people-agents.md): speech transcription goes through `SpeechProvider`;
the vendor and model are config (`config/speech.yaml`), the only vendor is Google (Gemini audio), dev and CI replay
a recording or use the fake, and a live call needs `LIVE=1`. No test here opens a network connection."""

from __future__ import annotations

import json
import pathlib
import re
from typing import Any

import pytest
import yaml
from _fake_genai_sdk import FakeAPIError, FakeClient, FakeGenerateContentResponse, FakeModelsAPI
from tilo_providers.config import ProviderConfigError
from tilo_providers.errors import ProviderError, QuotaError, RequestError
from tilo_providers.interfaces import SpeechProvider
from tilo_providers.replay import ReplayMissError
from tilo_providers.speech import (
    FakeSpeechProvider,
    SpeechConfig,
    SpeechRecordReplayProvider,
    as_speech_result,
    build_speech_provider,
    load_speech_config,
    speech_recording_key,
)

REPO = pathlib.Path(__file__).resolve().parents[3]
AUDIO = b"fixture-audio-bytes" * 10
SEGMENTS = [
    {"speaker": "Speaker 1", "start_ms": 0, "text": "Hello."},
    {"speaker": "Speaker 2", "start_ms": 900, "text": "Hi."},
]
CONFIG = SpeechConfig(
    vendor="google", profile_id="google-audio", model="speech-model-x", max_bytes=10_000, max_duration_ms=60_000
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("LIVE", "TILO_RECORD", "K_SERVICE", "CLOUD_RUN_JOB"):
        monkeypatch.delenv(name, raising=False)


def write_speech_yaml(tmp_path: pathlib.Path, **overrides: Any) -> pathlib.Path:
    speech = {
        "vendor": "google",
        "profile": "google-audio",
        "model": "speech-model-x",
        "max_bytes": 1000,
        "max_duration_ms": 5000,
    }
    speech.update(overrides)
    path = tmp_path / "speech.yaml"
    path.write_text(yaml.safe_dump({"speech": {k: v for k, v in speech.items() if v is not None}}), encoding="utf-8")
    return path


def test_FR_MTG_17_real_config_names_google_and_sane_caps():
    config = load_speech_config(REPO / "config" / "speech.yaml", models_path=REPO / "config" / "models.yaml")
    assert config.vendor == "google" and config.model and config.profile_id
    assert 0 < config.max_bytes <= 200_000_000 and 0 < config.max_duration_ms <= 6 * 3_600_000


@pytest.mark.parametrize(
    "overrides",
    [
        {"vendor": "elevenlabs"},
        {"vendor": "deepgram"},
        {"vendor": "openai"},
        {"vendor": ""},
        {"vendor": None},
        {"model": None},
        {"max_bytes": 0},
        {"max_bytes": "big"},
        {"max_bytes": True},
        {"max_duration_ms": -1},
    ],
)
def test_FR_MTG_17_bad_speech_config_fails_loudly(tmp_path, overrides):
    with pytest.raises(ProviderConfigError):
        load_speech_config(write_speech_yaml(tmp_path, **overrides), models_path=tmp_path / "none.yaml")


def test_FR_MTG_17_denylisted_speech_model_id_fails_startup(tmp_path):
    models = tmp_path / "models.yaml"
    models.write_text(yaml.safe_dump({"rules": {"deny": ["gemini-2.5-*", "*-preview*"]}}), encoding="utf-8")
    with pytest.raises(ProviderConfigError, match="denied"):
        load_speech_config(write_speech_yaml(tmp_path, model="gemini-2.5-flash"), models_path=models)
    with pytest.raises(ProviderConfigError, match="denied"):
        load_speech_config(write_speech_yaml(tmp_path, model="some-audio-preview"), models_path=models)


def test_FR_MTG_17_fake_speech_provider_is_deterministic_and_valid():
    fake = FakeSpeechProvider()
    first, second = fake.transcribe(AUDIO, media_type="audio/mpeg"), fake.transcribe(AUDIO, media_type="audio/mpeg")
    assert first == second == as_speech_result(first)
    assert fake.transcribe(AUDIO + b"x", media_type="audio/mpeg") != first
    assert FakeSpeechProvider(segments=SEGMENTS).transcribe(AUDIO, media_type="audio/mpeg") == {"segments": SEGMENTS}


@pytest.mark.parametrize("var", ["LIVE", "K_SERVICE", "CLOUD_RUN_JOB"])
def test_FR_MTG_17_fake_speech_provider_refused_when_live_or_deployed(monkeypatch, var):
    monkeypatch.setenv(var, "1" if var == "LIVE" else "")
    with pytest.raises(ProviderConfigError):
        FakeSpeechProvider()


def test_FR_MTG_17_factory_builds_fake_or_replay_and_refuses_any_other_vendor(tmp_path):
    assert isinstance(
        build_speech_provider(SpeechConfig("fake", "f", "fake-speech", 1, 1), fixtures_dir=tmp_path), FakeSpeechProvider
    )
    assert isinstance(build_speech_provider(CONFIG, fixtures_dir=tmp_path), SpeechRecordReplayProvider)
    for vendor in ("elevenlabs", "deepgram", "assemblyai", "openai", "azure", "aws"):
        with pytest.raises(ProviderConfigError):
            build_speech_provider(SpeechConfig(vendor, "p", "m", 1, 1), fixtures_dir=tmp_path)


def test_FR_MTG_17_replay_miss_names_the_key_and_never_goes_live(tmp_path):
    provider = build_speech_provider(CONFIG, fixtures_dir=tmp_path)
    with pytest.raises(ReplayMissError, match=speech_recording_key("google-audio", AUDIO, "audio/mpeg", None)):
        provider.transcribe(AUDIO, media_type="audio/mpeg")  # the socket guard would fail any real call


def test_FR_MTG_17_record_then_replay_round_trip_keeps_audio_and_secrets_out_of_the_recording(tmp_path, monkeypatch):
    # The fake refuses to be built in live mode, so build it first and switch live mode on for the call only.
    live = FakeSpeechProvider(segments=[{**SEGMENTS[0], "text": "Authorization: Bearer abc.def-ghi"}, SEGMENTS[1]])
    provider = SpeechRecordReplayProvider("google-audio", lambda: live, tmp_path, max_bytes=10_000)
    monkeypatch.setenv("LIVE", "1")
    monkeypatch.setenv("TILO_RECORD", "1")
    provider.transcribe(AUDIO, media_type="audio/mpeg")
    monkeypatch.delenv("LIVE")
    monkeypatch.delenv("TILO_RECORD")
    (file,) = (tmp_path / "speech-recordings").glob("*.json")
    assert file.stem == speech_recording_key("google-audio", AUDIO, "audio/mpeg", None)
    text = file.read_text(encoding="utf-8")
    assert "abc.def-ghi" not in text and AUDIO.decode() not in text
    replayed = provider.transcribe(AUDIO, media_type="audio/mpeg")  # replay: the live provider is not touched
    assert replayed == as_speech_result(json.loads(text)["result"])
    assert replayed["segments"][1] == SEGMENTS[1] and "[redacted]" in replayed["segments"][0]["text"]


def test_FR_MTG_17_recording_key_depends_on_profile_audio_media_type_and_language():
    keys = {
        speech_recording_key("p", AUDIO, "audio/mpeg", None),
        speech_recording_key("q", AUDIO, "audio/mpeg", None),
        speech_recording_key("p", AUDIO + b"x", "audio/mpeg", None),
        speech_recording_key("p", AUDIO, "audio/wav", None),
        speech_recording_key("p", AUDIO, "audio/mpeg", "en"),
    }
    assert len(keys) == 5


def test_FR_MTG_17_replay_fails_closed_on_a_corrupt_or_malformed_recording(tmp_path):
    provider = SpeechRecordReplayProvider("google-audio", lambda: FakeSpeechProvider(), tmp_path, max_bytes=10_000)
    path = tmp_path / "speech-recordings" / f"{speech_recording_key('google-audio', AUDIO, 'audio/mpeg', None)}.json"
    path.parent.mkdir(parents=True)
    for body in ("{not json", "[]", json.dumps({"result": {"segments": [{"text": "x"}]}}), json.dumps({"nope": 1})):
        path.write_text(body, encoding="utf-8")
        with pytest.raises(ProviderError):
            provider.transcribe(AUDIO, media_type="audio/mpeg")


def test_FR_MTG_17_input_over_the_byte_cap_is_refused_before_lookup_or_live(tmp_path):
    called = []
    provider = SpeechRecordReplayProvider(
        "g", lambda: called.append(1) or FakeSpeechProvider(), tmp_path, max_bytes=100
    )
    with pytest.raises(RequestError):
        provider.transcribe(b"x" * 101, media_type="audio/mpeg")
    with pytest.raises(RequestError):
        provider.transcribe(b"", media_type="audio/mpeg")
    with pytest.raises(RequestError):
        provider.transcribe(AUDIO)  # no media type: fails closed
    assert called == []


# --- the Google adapter (Gemini audio), against a fake SDK client only ---------------------------------------------


def google_provider(client: Any, **kwargs: Any):
    from tilo_providers.google_speech_adapter import GoogleSpeechProvider

    return GoogleSpeechProvider(
        model="speech-model-x", project="demo-project", location="global", client=client, **kwargs
    )


def client_returning(text: str | None = None, error: Exception | None = None) -> FakeClient:
    return FakeClient(
        FakeModelsAPI(generate_content_result=FakeGenerateContentResponse(text=text), generate_content_error=error)
    )


def test_FR_MTG_17_google_adapter_refuses_to_build_a_client_without_live(fake_genai_sdk):
    from tilo_providers.google_speech_adapter import GoogleSpeechProvider

    with pytest.raises(ProviderError, match="LIVE=1"):
        GoogleSpeechProvider(model="speech-model-x", project="demo-project", location="global")


def test_FR_MTG_17_google_adapter_sends_the_audio_inline_and_parses_segments(fake_genai_sdk):
    client = client_returning(json.dumps({"segments": SEGMENTS}))
    result = google_provider(client).transcribe(AUDIO, media_type="audio/mpeg")
    assert result == {"segments": SEGMENTS}
    (call,) = client.models.calls
    assert call["model"] == "speech-model-x"
    parts = json.dumps(call["contents"], default=lambda b: f"<{len(b)} bytes>")
    assert f"<{len(AUDIO)} bytes>" in parts and "audio/mpeg" in parts
    assert (
        getattr(call["config"], "response_mime_type", None) == "application/json"
        or call["config"]["response_mime_type"] == "application/json"
    )


@pytest.mark.parametrize("text", [None, "", "not json", "[]", '{"segments": "x"}', '{"segments": [{"text": 1}]}'])
def test_FR_MTG_17_google_adapter_fails_closed_on_a_bad_reply(fake_genai_sdk, text):
    with pytest.raises(ProviderError):
        google_provider(client_returning(text)).transcribe(AUDIO, media_type="audio/mpeg")


def test_FR_MTG_17_google_adapter_maps_errors_and_never_echoes_a_token(fake_genai_sdk):
    with pytest.raises(QuotaError) as excinfo:
        google_provider(client_returning(error=FakeAPIError(429, "quota ya29.SECRET-token-value"))).transcribe(
            AUDIO, media_type="audio/mpeg"
        )
    assert "SECRET-token-value" not in str(excinfo.value)
    with pytest.raises(ProviderError):
        google_provider(client_returning(error=ValueError("boom"))).transcribe(AUDIO, media_type="audio/mpeg")


def test_FR_MTG_17_google_adapter_needs_a_media_type_and_audio(fake_genai_sdk):
    provider = google_provider(client_returning(json.dumps({"segments": SEGMENTS})))
    with pytest.raises(RequestError):
        provider.transcribe(AUDIO)
    with pytest.raises(RequestError):
        provider.transcribe(b"", media_type="audio/mpeg")


def test_FR_MTG_17_the_transcribe_prompt_is_a_template_not_a_string_in_code():
    from tilo_providers.prompts import load_prompt

    assert "Language of the recording: en-GB" in load_prompt("speech", "transcribe.md", {"language": "en-GB"})
    code = (REPO / "packages/providers/src/tilo_providers/google_speech_adapter.py").read_text(encoding="utf-8")
    assert "load_prompt(" in code


# --- Google only ---------------------------------------------------------------------------------------------------

NON_GOOGLE = re.compile(
    r"eleven\s*labs|deepgram|assembly\s*ai|whisper|speechmatics|gladia|vosk|nuance|watson|rev\.ai"
    r"|azure|amazon\s+transcribe|aws\s+transcribe|openai(?![_-]compat)",
    re.I,
)


def _speech_files() -> list[pathlib.Path]:
    files = [
        *(REPO / "packages/providers/src/tilo_providers").glob("*speech*.py"),
        REPO / "config" / "speech.yaml",
        REPO / ".env.example",
        REPO / "packages/planning/src/tilo_planning/recording.py",
        *(REPO / "prompts" / "speech").glob("*"),
    ]
    assert len(files) >= 6, files
    return files


def test_FR_MTG_17_no_non_google_speech_vendor_in_code_config_prompts_or_env_example():
    for path in _speech_files():
        match = NON_GOOGLE.search(path.read_text(encoding="utf-8"))
        assert match is None, f"{path}: {match.group(0) if match else ''}"


def test_FR_MTG_17_no_non_google_speech_dependency_in_any_pyproject():
    manifests = [
        *REPO.glob("pyproject.toml"),
        *REPO.glob("packages/*/pyproject.toml"),
        *REPO.glob("services/*/pyproject.toml"),
    ]
    assert manifests
    for path in manifests:
        match = NON_GOOGLE.search(path.read_text(encoding="utf-8"))
        assert match is None, f"{path}: {match.group(0) if match else ''}"


def test_FR_MTG_17_only_google_fake_and_replay_speech_providers_exist():
    import tilo_providers.google_speech_adapter  # noqa: F401
    import tilo_providers.speech  # noqa: F401

    def walk(cls: type) -> set[type]:
        return {cls}.union(*(walk(sub) for sub in cls.__subclasses__()))

    ours = {c.__name__ for c in walk(SpeechProvider) if c.__module__.startswith("tilo_providers")}
    assert ours == {
        "SpeechProvider",
        "FakeSpeechProvider",
        "SpeechRecordReplayProvider",
        "GoogleSpeechProvider",
        "GoogleVoiceProvider",  # FR-MTG-11: Gemini speech output behind the live switch (tilo_providers.voice)
    }
