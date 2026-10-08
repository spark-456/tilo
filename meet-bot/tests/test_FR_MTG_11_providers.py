"""FR-MTG-11: every model and speech call of the bot goes through `bot/providers.py` onto `packages/providers`. Offline:
scripted providers behind a real Router, the dev config's fakes, no network, no key."""

import asyncio
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from tilo_providers.config import load_providers_config
from tilo_providers.errors import QuotaError, RequestError, RetryableError
from tilo_providers.fake import FakeModelProvider
from tilo_providers.interfaces import GenerateRequest, GenerateResponse
from tilo_providers.router import Router
from tilo_providers.speech import FakeSpeechProvider

from bot import providers as P
from bot.brain import Busy, LLMUnavailable
from bot.llm_fast import FastLLM, ModelCallError

REPO = Path(__file__).resolve().parents[2]


class Scripted(FakeModelProvider):
    """One behaviour per call: a reply text, or an exception to raise."""

    def __init__(self, *script: Any) -> None:
        super().__init__("meeting-fake")
        self.script, self.requests = list(script), []

    def _next(self, request: GenerateRequest) -> str:
        self.requests.append(request)
        step = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(step, Exception):
            raise step
        return step

    def generate(self, request: GenerateRequest) -> GenerateResponse:
        return GenerateResponse(text=self._next(request), profile_id="meeting-fake")

    def stream(self, request: GenerateRequest) -> Iterator[GenerateResponse]:
        text = self._next(request)
        for piece in text.split("|"):
            yield GenerateResponse(text=piece, profile_id="meeting-fake")


def router_for(provider: Scripted) -> Router:
    config = load_providers_config(REPO / "config" / "models.dev.yaml", REPO / "config" / "prices.yaml")
    return Router(config, provider_for_profile=lambda profile_id: provider)


def run(coro):
    return asyncio.run(coro)


# -- config resolution -----------------------------------------------------------------------------------------------
def test_FR_MTG_11_without_the_live_switch_the_dev_config_with_fakes_is_used():
    assert P.models_file().name == "models.dev.yaml" and P.speech_file().name == "speech.dev.yaml"
    config = P.load_config()
    for role in (P.BRAIN_ROLE, P.FAST_ROLE):
        assert config.profiles[config.roles[role].primary].provider == "fake"


def test_FR_MTG_11_the_live_switch_selects_the_real_roles_and_speech_config(monkeypatch):
    monkeypatch.setenv("LIVE", "1")  # selection only: nothing is built or called here
    assert P.models_file().name == "models.yaml" and P.speech_file().name == "speech.yaml"
    monkeypatch.setenv("TILO_MODELS_FILE", str(REPO / "config" / "models.nim.yaml"))
    assert P.models_file().name == "models.nim.yaml"


def test_FR_MTG_11_the_shipped_roles_exist_in_every_models_file_with_caps_and_a_fallback():
    for name in ("models.yaml", "models.nim.yaml", "models.gemini.yaml", "models.dev.yaml"):
        config = load_providers_config(REPO / "config" / name, REPO / "config" / "prices.yaml")
        for role in (P.BRAIN_ROLE, P.FAST_ROLE):
            r = config.roles[role]
            assert r.fallback and r.max_input_tokens and r.max_output_tokens, (name, role)


# -- the analysis model ----------------------------------------------------------------------------------------------
def test_FR_MTG_11_the_brain_model_is_the_meeting_role_with_system_prompt_and_json_mode():
    provider = Scripted('{"ok": true}')
    llm = P.ProviderLLM(router_for(provider))
    assert llm.generate("be brief", "INPUT_JSON:{}") == '{"ok": true}'
    (request,) = provider.requests
    assert request.system == "be brief" and request.json_mode and request.max_output_tokens == 2048  # the role's cap


def test_FR_MTG_11_default_dev_run_returns_deterministic_fake_text_offline():
    llm = P.ProviderLLM()
    first, second = llm.generate("s", "p"), llm.generate("s", "p")
    assert first == second and first.startswith("[fake:")


def test_FR_MTG_11_a_throttled_project_backs_off_then_succeeds():
    sleeps: list[float] = []
    provider = Scripted(QuotaError("429"), RetryableError("503"), "{}")
    llm = P.ProviderLLM(router_for(provider), sleep=sleeps.append)
    assert llm.generate("s", "p") == "{}"
    assert sleeps == [2.0, 4.0]


def test_FR_MTG_11_quota_exhaustion_is_busy_with_a_clear_message():
    llm = P.ProviderLLM(router_for(Scripted(QuotaError("429"))), sleep=lambda s: None, max_attempts=3)
    with pytest.raises(Busy, match="quota"):
        llm.generate("s", "p")


def test_FR_MTG_11_a_refused_request_fails_fast_without_retries_and_without_provider_text():
    secret = "tok-" + "9f3a" * 6  # assembled at runtime, never a real secret
    provider = Scripted(RequestError(f"403 PERMISSION_DENIED {secret}"))
    llm = P.ProviderLLM(router_for(provider), sleep=lambda s: pytest.fail("a refusal must not sleep"))
    with pytest.raises(LLMUnavailable) as exc:
        llm.generate("s", "p")
    assert len(provider.requests) == 1 and secret not in str(exc.value) and "credentials" in str(exc.value)


# -- the fast model --------------------------------------------------------------------------------------------------
def test_FR_MTG_11_the_fast_client_streams_the_meeting_fast_role_in_order():
    provider = Scripted("Hi |there|.")
    client = P.ProviderFastClient(router_for(provider))
    llm = FastLLM(lambda: client, thinking="minimal", first_token_s=5)
    assert run(llm.generate("sys", "q", json_mode=True, max_tokens=64)) == "Hi there."
    (request,) = provider.requests
    assert request.thinking_level == "minimal" and request.max_output_tokens == 64 and request.json_mode


def test_FR_MTG_11_thinking_off_sends_no_thinking_level():
    provider = Scripted("ok")
    llm = FastLLM(lambda: P.ProviderFastClient(router_for(provider)), thinking="off", first_token_s=5)
    run(llm.generate("sys", "q"))
    assert provider.requests[0].thinking_level is None


def test_FR_MTG_11_a_quota_error_on_the_fast_path_is_busy_and_a_refusal_is_unavailable():
    llm = FastLLM(lambda: P.ProviderFastClient(router_for(Scripted(QuotaError("429")))), first_token_s=5)
    with pytest.raises(Busy):
        run(llm.generate("sys", "q"))
    llm = FastLLM(lambda: P.ProviderFastClient(router_for(Scripted(RequestError("403")))), first_token_s=5)
    with pytest.raises(LLMUnavailable):
        run(llm.generate("sys", "q"))


def test_FR_MTG_11_the_provider_fast_client_has_nothing_to_warm_so_no_prewarm_is_logged():
    rows: list[dict] = []
    llm = FastLLM(lambda: P.ProviderFastClient(router_for(Scripted("x"))), on_attempt=rows.append, first_token_s=5)
    assert run(P.ProviderFastClient(router_for(Scripted("x"))).warm()) is False
    run(llm.prewarm())
    assert rows == []


def test_FR_MTG_11_call_errors_carry_codes_not_provider_text():
    err = P.call_error(QuotaError("secret"))
    assert (err.code, err.status) == (429, "RESOURCE_EXHAUSTED") and "secret" not in str(err)
    assert (
        isinstance(P.call_error(RetryableError("x")), ModelCallError) and P.call_error(RetryableError("x")).code is None
    )


# -- speech ----------------------------------------------------------------------------------------------------------
def test_FR_MTG_11_speech_to_text_goes_through_the_speech_provider_as_wav_batch_audio():
    seen: dict[str, Any] = {}

    class Recording(FakeSpeechProvider):
        def transcribe(self, audio: bytes, **kwargs: Any) -> Any:
            seen.update(kwargs, size=len(audio))
            return {
                "segments": [
                    {"speaker": "Speaker 1", "start_ms": 0, "text": " Hello "},
                    {"speaker": "S2", "start_ms": 5, "text": "there."},
                ]
            }

    speech = P.ProviderSpeech(Recording())
    assert speech.text(b"RIFF" + bytes(40)) == "Hello there."
    assert seen["media_type"] == "audio/wav" and seen["language"] == "en" and seen["size"] == 44


def test_FR_MTG_11_the_default_speech_provider_is_the_deterministic_fake_offline():
    text = P.ProviderSpeech().text(b"RIFF" + bytes(40))
    assert text.startswith("[fake:") and text == P.ProviderSpeech().text(b"RIFF" + bytes(40))


def test_FR_MTG_11_a_speech_failure_is_an_unavailable_model_with_a_class_name_only():
    class Failing(FakeSpeechProvider):
        def transcribe(self, audio: bytes, **kwargs: Any) -> Any:
            raise RuntimeError("boom with a secret")

    with pytest.raises(LLMUnavailable) as exc:
        P.ProviderSpeech(Failing()).text(b"x")
    assert "secret" not in str(exc.value) and "RuntimeError" in str(exc.value)


def test_FR_MTG_11_retranscribe_writes_the_providers_segments_with_offsets(tmp_path):
    import struct
    import wave

    from bot.retranscribe import retranscribe

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    with wave.open(str(run_dir / "audio.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(struct.pack("<" + "h" * 16000, *([8000, -8000] * 8000)))  # one second of loud signal
    seen: list[int] = []

    def transcribe(wav: bytes) -> list[dict[str, Any]]:
        seen.append(len(wav))
        return [
            {"speaker": "Speaker 1", "start_ms": 2500, "text": "Hello."},
            {"speaker": "S2", "start_ms": 0, "text": " "},
        ]

    out = retranscribe(run_dir, transcribe)
    text = out.read_text(encoding="utf-8")
    assert seen and "[00:02] Speaker 1: Hello." in text and "S2" not in text
