"""FR-MTG-11 (closes BQ-MTG11-2/-3): the bot's voice is Google Cloud Text-to-Speech, a Chirp 3 HD voice, by STREAMING
synthesis, so the first audio reaches the meeting about a second after the first reply text. Tested against a fake
streaming client and a fake `google.cloud.texttospeech` module only: no network, no SDK, no live switch."""

from __future__ import annotations

import logging
import pathlib
import re
import sys
import types
from types import SimpleNamespace
from typing import Any

import pytest
import yaml
from tilo_providers.config import ProviderConfigError
from tilo_providers.errors import NotConfigured, ProviderError, QuotaError, RequestError, RetryableError
from tilo_providers.interfaces import SpeechProvider
from tilo_providers.voice import VoiceConfig, build_voice_provider, load_voice_config

REPO = pathlib.Path(__file__).resolve().parents[3]
VOICE = "en-US-Chirp3-HD-Test"
CHIRP = VoiceConfig("google-cloud-tts", "chirp3-hd", "chirp-3-hd", VOICE, 24000, 400, 100_000, "asia-southeast1", 7.0)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("LIVE", "TILO_RECORD", "K_SERVICE", "CLOUD_RUN_JOB", "GOOGLE_VERTEX_BASE_URL"):
        monkeypatch.delenv(name, raising=False)


class ApiError(Exception):
    """Shaped like google.api_core's GoogleAPICallError: an HTTP status in `code`, the text in `message`."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


class FakeStreamingClient:
    """Records the requests and the timeout; hands the responses out lazily so a test can see what had been pulled."""

    def __init__(self, chunks: list[Any], error_at: int | None = None, error: Exception | None = None) -> None:
        self.chunks, self.error_at, self.error = chunks, error_at, error
        self.requests: list[Any] = []
        self.timeout: Any = None
        self.pulled = 0

    def streaming_synthesize(self, requests: Any, timeout: Any = None) -> Any:
        self.timeout = timeout
        self.requests = list(requests)

        def responses() -> Any:
            for i, chunk in enumerate(self.chunks):
                if self.error is not None and i == self.error_at:
                    raise self.error
                self.pulled += 1
                yield SimpleNamespace(audio_content=chunk)
            if self.error is not None and self.error_at is None:
                raise self.error

        return responses()


def provider(client: Any, **kwargs: Any):
    from tilo_providers.cloud_tts_adapter import GoogleCloudTTSProvider

    defaults: dict[str, Any] = {
        "voice": VOICE,
        "sample_rate": 24000,
        "project": "demo-project",
        "region": "asia-southeast1",
        "timeout_s": 7.0,
        "client": client,
    }
    return GoogleCloudTTSProvider(**{**defaults, **kwargs})


A, B, C = bytes(range(0, 200, 2)), bytes(range(1, 201, 2)), bytes(100)  # three even-length PCM chunks


# --- config ---------------------------------------------------------------------------------------------------------


def test_FR_MTG_11_the_real_voice_config_names_a_chirp_3_hd_voice_on_cloud_tts_in_the_region():
    cfg = load_voice_config(REPO / "config" / "voice.yaml", models_path=REPO / "config" / "models.yaml")
    assert cfg.vendor == "google-cloud-tts" and re.fullmatch(r"[a-z]{2,3}-[A-Z]{2}-Chirp3-HD-[A-Za-z]+", cfg.voice)
    assert cfg.region == "asia-southeast1" and 0 < cfg.timeout_s <= 30 and cfg.sample_rate == 24000
    dev = load_voice_config(REPO / "config" / "voice.dev.yaml", models_path=REPO / "config" / "models.yaml")
    assert dev.vendor == "fake" and dev.region == "global"


def test_FR_MTG_11_the_chirp_profile_is_priced_per_character_at_the_adr_0029_rate():
    cfg = load_voice_config(REPO / "config" / "voice.yaml", models_path=REPO / "config" / "models.yaml")
    prices = yaml.safe_load((REPO / "config" / "prices.yaml").read_text(encoding="utf-8"))
    row = prices["profiles"][cfg.profile_id]
    assert row["unit_price"] == {"unit": "character", "per_1k": 0.03}  # US$30 per 1M characters, no free allowance
    assert "valid_until" not in row  # Chirp 3 HD has no promotion (ADR-0029 decision 4)


@pytest.mark.parametrize("overrides", [{"region": "not a region"}, {"region": "http://evil"}, {"timeout_s": 0}])
def test_FR_MTG_11_a_bad_region_or_timeout_fails_startup_loudly(tmp_path, overrides):
    voice = {
        "vendor": "google-cloud-tts",
        "profile": "p",
        "model": "m",
        "voice": VOICE,
        "sample_rate": 24000,
        "max_chars": 400,
        "max_audio_bytes": 1000,
        **overrides,
    }
    path = tmp_path / "voice.yaml"
    path.write_text(yaml.safe_dump({"voice": voice}), encoding="utf-8")
    with pytest.raises(ProviderConfigError):
        load_voice_config(path, models_path=tmp_path / "none.yaml")


# --- the streaming adapter ------------------------------------------------------------------------------------------


def test_FR_MTG_11_the_first_audio_chunk_is_forwarded_before_the_rest_is_pulled():
    client = FakeStreamingClient([A, B, C])
    stream = provider(client).synthesize_stream("Hello there.")
    assert next(stream) == A
    assert client.pulled == 1  # the second chunk had not been asked for: the bot can start speaking now
    assert list(stream) == [B, C]


def test_FR_MTG_11_the_request_is_a_config_then_the_text_with_the_voice_rate_and_timeout():
    client = FakeStreamingClient([A])
    assert b"".join(provider(client).synthesize_stream("Hello there.")) == A
    config, text = client.requests
    streaming = config["streaming_config"]
    assert streaming["voice"] == {"name": VOICE, "language_code": "en-US"}
    assert streaming["streaming_audio_config"] == {"audio_encoding": "PCM", "sample_rate_hertz": 24000}
    assert text == {"input": {"text": "Hello there."}}
    assert client.timeout == 7.0  # the SDK call has a deadline


def test_FR_MTG_11_synthesize_joins_the_stream_and_a_per_call_voice_wins():
    client = FakeStreamingClient([A, B])
    assert provider(client).synthesize("Hi.", voice="fr-FR-Chirp3-HD-Other") == A + B
    assert client.requests[0]["streaming_config"]["voice"] == {
        "name": "fr-FR-Chirp3-HD-Other",
        "language_code": "fr-FR",
    }


def test_FR_MTG_11_pcm_stays_16_bit_aligned_across_chunk_edges_and_a_wav_header_is_dropped():
    wav = b"RIFF" + b"\x00" * 4 + b"WAVEfmt " + b"\x10\x00\x00\x00" + b"\x01\x00\x01\x00\xc0]\x00\x00\x80\xbb\x00\x00"
    wav += b"\x02\x00\x10\x00" + b"data" + b"\xff\xff\xff\xff"  # a 44-byte header with an open-ended data size
    pcm = bytes(range(1, 41))
    client = FakeStreamingClient([wav + pcm[:7], pcm[7:20], pcm[20:]])
    chunks = list(provider(client).synthesize_stream("Hello"))
    assert b"".join(chunks) == pcm and all(len(c) % 2 == 0 for c in chunks)


@pytest.mark.parametrize("chunks", [[], [b""], [b"", b""], [b"\x01"]])
def test_FR_MTG_11_no_audio_or_a_dangling_byte_fails_closed(chunks):
    with pytest.raises(ProviderError):
        list(provider(FakeStreamingClient(chunks)).synthesize_stream("Hello"))


def test_FR_MTG_11_the_audio_cap_stops_the_stream_before_the_chunk_that_crosses_it():
    client = FakeStreamingClient([A, B, C])
    stream = provider(client, max_audio_bytes=len(A) + 10).synthesize_stream("Hello")
    assert next(stream) == A
    with pytest.raises(ProviderError, match="cap"):
        next(stream)


def test_FR_MTG_11_text_over_the_char_cap_or_a_bad_voice_is_refused_before_any_request():
    client = FakeStreamingClient([A])
    tts = provider(client, max_chars=10)
    with pytest.raises(RequestError):
        list(tts.synthesize_stream("x" * 11))
    with pytest.raises(RequestError):
        list(tts.synthesize_stream("Hello", voice="bad voice!"))
    with pytest.raises(RequestError):
        list(tts.synthesize_stream("Hello", voice="Kore"))  # not a locale-prefixed Cloud TTS voice name
    with pytest.raises(RequestError):
        list(tts.synthesize_stream("Hello", speed=2))
    assert client.requests == []


def test_FR_MTG_11_errors_map_onto_provider_errors_and_never_echo_a_token():
    with pytest.raises(QuotaError) as excinfo:
        list(
            provider(FakeStreamingClient([], error=ApiError(429, "quota ya29.SECRET-token-value"))).synthesize_stream(
                "Hi"
            )
        )
    assert "SECRET-token-value" not in str(excinfo.value)
    with pytest.raises(RetryableError):
        list(provider(FakeStreamingClient([], error=ApiError(503, "unavailable"))).synthesize_stream("Hi"))
    with pytest.raises(RequestError):
        list(provider(FakeStreamingClient([], error=ApiError(400, "bad voice"))).synthesize_stream("Hi"))
    with pytest.raises(ProviderError):  # a failure after the first chunk surfaces on the next pull
        list(provider(FakeStreamingClient([A, B], error_at=1, error=ValueError("boom"))).synthesize_stream("Hi"))


def test_FR_MTG_11_timing_counts_characters_and_first_audio_latency_and_carries_no_text(caplog):
    ticks = iter([10.0, 10.4, 11.0])  # start, first audio, end
    seen: list[Any] = []
    tts = provider(FakeStreamingClient([A, B]), clock=lambda: next(ticks), on_timing=seen.append)
    with caplog.at_level(logging.INFO, logger="tilo_providers.voice"):
        list(tts.synthesize_stream("Secret meeting words."))
    (timing,) = seen
    assert tts.last_timing == timing
    assert timing.characters == len("Secret meeting words.") and timing.chunks == 2
    assert timing.audio_bytes == len(A) + len(B)
    assert timing.first_audio_ms == pytest.approx(400) and timing.total_ms == pytest.approx(1000)
    assert "first_audio_ms=400" in caplog.text and "Secret" not in caplog.text and "meeting" not in caplog.text
    assert not any(hasattr(timing, name) for name in ("text", "voice", "audio"))


# --- the live switch and the real client ----------------------------------------------------------------------------


def test_FR_MTG_11_a_real_client_is_not_built_without_the_live_switch():
    from tilo_providers.cloud_tts_adapter import GoogleCloudTTSProvider

    with pytest.raises(ProviderError, match="LIVE=1"):
        GoogleCloudTTSProvider(voice=VOICE, sample_rate=24000, project="demo-project", region="asia-southeast1")


def test_FR_MTG_11_the_factory_builds_the_cloud_voice_and_it_makes_no_call_without_the_live_switch(tmp_path):
    voice = build_voice_provider(CHIRP, fixtures_dir=tmp_path)
    assert isinstance(voice, SpeechProvider)
    with pytest.raises(NotConfigured, match="LIVE"):
        voice.synthesize("Hello")
    with pytest.raises(NotConfigured, match="LIVE"):
        list(voice.synthesize_stream("Hello"))


def test_FR_MTG_11_the_cloud_voice_enforces_the_config_char_cap_before_the_live_check(tmp_path):
    cfg = VoiceConfig("google-cloud-tts", "p", "m", VOICE, 24000, 10, 1000)
    with pytest.raises(RequestError):
        list(build_voice_provider(cfg, fixtures_dir=tmp_path).synthesize_stream("x" * 11))


def test_FR_MTG_11_the_live_voice_streams_through_the_config_audio_cap(tmp_path, monkeypatch):
    cfg = VoiceConfig("google-cloud-tts", "p", "m", VOICE, 24000, 400, len(A) + 10)
    voice = build_voice_provider(cfg, fixtures_dir=tmp_path)
    monkeypatch.setenv("LIVE", "1")
    voice._live = provider(FakeStreamingClient([A, B]), max_audio_bytes=None)  # an injected adapter; no client is built
    stream = voice.synthesize_stream("Hello")
    assert next(stream) == A
    with pytest.raises(ProviderError, match="cap"):
        next(stream)


def test_FR_MTG_11_the_real_client_uses_the_regional_endpoint_and_wraps_requests_for_the_sdk(monkeypatch):
    built: dict[str, Any] = {}

    class Request:
        def __init__(self, mapping: dict[str, Any]) -> None:
            self.mapping = mapping

    class SdkClient:
        def __init__(self, client_options: dict[str, Any]) -> None:
            built["options"] = client_options

        def streaming_synthesize(self, requests: Any, timeout: Any = None) -> Any:
            built["requests"] = [r.mapping for r in requests]
            built["timeout"] = timeout
            return iter([SimpleNamespace(audio_content=A)])

    module = types.ModuleType("google.cloud.texttospeech")
    module.TextToSpeechClient = SdkClient  # type: ignore[attr-defined]
    module.StreamingSynthesizeRequest = Request  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "google.cloud.texttospeech", module)
    monkeypatch.setenv("LIVE", "1")
    from tilo_providers.cloud_tts_adapter import GoogleCloudTTSProvider

    tts = GoogleCloudTTSProvider(
        voice=VOICE, sample_rate=24000, project="demo-project", region="asia-southeast1", timeout_s=7.0
    )
    assert b"".join(tts.synthesize_stream("Hello")) == A
    assert built["options"]["api_endpoint"] == "asia-southeast1-texttospeech.googleapis.com"
    assert built["timeout"] == 7.0 and len(built["requests"]) == 2
    monkeypatch.setenv("GOOGLE_VERTEX_BASE_URL", "https://evil.example")  # the shared Google settings guard applies
    with pytest.raises(ProviderError):
        GoogleCloudTTSProvider(voice=VOICE, sample_rate=24000, project="demo-project", region="asia-southeast1")


def test_FR_MTG_11_the_global_region_uses_the_default_endpoint(monkeypatch):
    options: dict[str, Any] = {}
    module = types.ModuleType("google.cloud.texttospeech")
    module.TextToSpeechClient = lambda client_options: options.update(client_options) or object()  # type: ignore[attr-defined]
    module.StreamingSynthesizeRequest = dict  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "google.cloud.texttospeech", module)
    monkeypatch.setenv("LIVE", "1")
    from tilo_providers.cloud_tts_adapter import GoogleCloudTTSProvider

    GoogleCloudTTSProvider(voice=VOICE, sample_rate=24000, project="demo-project", region="global")
    assert "api_endpoint" not in options
