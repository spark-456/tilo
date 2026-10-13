"""The one module in meet-bot that talks to Tilo's provider layer (FR-MTG-11, PL-01).

Everything the bot needs from a model or a speech service goes through here and nowhere else:

- `ProviderLLM`: the `LLM` protocol of `brain.py` on the `meeting` role (agenda analysis, JSON in and out).
- `ProviderFastClient`: the client behind `FastLLM` (`llm_fast.py`) on the `meeting_fast` role (direct answers).
- `ProviderSpeech`: audio to text through `SpeechProvider` (the hybrid transcript and `retranscribe`).
- `ProviderTTS` and `make_tts`: the bot's voice through `SpeechProvider.synthesize` (`config/voice.yaml`).

Every one of those calls is counted against the meeting's cap (`config/meeting.yaml`, `call_counter()`): outside
participants can make the bot ask, and the bot's calls run outside the router's budget. At the cap the call is
refused before any request, a warning is logged once, and the bot degrades (no more answers, the local voice,
captions only).

The bot never names a model, a vendor or a key. Roles, profiles, the speech vendor and the caps are Tilo config
(`config/models*.yaml`, `config/speech*.yaml`); credentials are Google's application default credentials, read by the
provider layer. Without `LIVE=1` (only the user sets it) the dev config resolves fake providers, so a test, a mock run
and a bot started by hand make no network call and no paid call. This file imports only `tilo_providers`, the standard
library and the bot's own modules; a test (`test_FR_MTG_11_*`) enforces it.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import AsyncIterator, Callable
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from tilo_providers.config import ProviderConfigError, ProvidersConfig, load_providers_config, profiles_used_by
from tilo_providers.errors import LiveVoiceRefused, NotConfigured, QuotaError, RequestError, RetryableError
from tilo_providers.interfaces import GenerateRequest, SpeechProvider
from tilo_providers.meeting import CallCounter, load_meeting_caps
from tilo_providers.router import Router, RouterError, TokenCapExceededError
from tilo_providers.speech import build_speech_provider, load_speech_config
from tilo_providers.voice import LiveVoiceMeter, VoiceConfig, build_voice_provider, load_voice_config

from .brain import Busy, LLMUnavailable
from .config import ROOT
from .guards import BotRefused, recording_refusal
from .llm_fast import CallCapReached, ModelCallError
from .tts import STT_END_AT, FallbackTTS, LocalTTS, TTSError, TTSProvider

log = logging.getLogger("bot.providers")
BRAIN_ROLE = "meeting"
FAST_ROLE = "meeting_fast"
WAV_TYPE = "audio/wav"


# -- where the config lives ----------------------------------------------------------------------------------------
def repo_root() -> Path:
    """The Tilo checkout (or, in the bot's container, the copy of `config/`, `prompts/` and `packages/` that the
    Dockerfile places under TILO_REPO_ROOT). The provider layer finds its prompts relative to its own package."""
    override = os.environ.get("TILO_REPO_ROOT", "").strip()
    return Path(override) if override else Path(__file__).resolve().parents[2]


def is_live() -> bool:
    return os.environ.get("LIVE") == "1"


def _config_file(env_name: str, live_name: str, dev_name: str) -> Path:
    override = os.environ.get(env_name, "").strip()
    if override:
        return Path(override)
    return repo_root() / "config" / (live_name if is_live() else dev_name)


def models_file() -> Path:
    """`TILO_MODELS_FILE`, else the real roles when LIVE=1, else the dev file whose profiles are fakes."""
    return _config_file("TILO_MODELS_FILE", "models.yaml", "models.dev.yaml")


def speech_file() -> Path:
    return _config_file("TILO_SPEECH_FILE", "speech.yaml", "speech.dev.yaml")


def voice_file() -> Path:
    return _config_file("TILO_VOICE_FILE", "voice.yaml", "voice.dev.yaml")


def meeting_file() -> Path:
    """`TILO_MEETING_FILE`, else `config/meeting.yaml` (one file: the caps are as conservative offline as live)."""
    override = os.environ.get("TILO_MEETING_FILE", "").strip()
    return Path(override) if override else repo_root() / "config" / "meeting.yaml"


def fixtures_dir() -> Path:
    return repo_root() / "fixtures"  # replay only: the bot refuses TILO_RECORD (guards.py), so it never writes here


# -- the per-meeting call cap ----------------------------------------------------------------------------------------
_counter: CallCounter | None = None
_counter_context: ContextVar[CallCounter | None] = ContextVar("meeting_call_counter", default=None)


def call_counter() -> CallCounter:
    """The request's counter. Executor threads inherit it even if a later request resets the process default."""
    global _counter
    counter = _counter_context.get()
    if counter is None:
        if _counter is None:
            _counter = CallCounter(load_meeting_caps(meeting_file()))
        counter = _counter
        _counter_context.set(counter)
    return counter


def set_call_counter(counter: CallCounter | None) -> None:
    global _counter
    _counter = counter
    _counter_context.set(counter)


def reset_call_counter() -> None:
    set_call_counter(None)


def take_call(kind: str) -> bool:
    """True if one more `model` or `speech` call may be made. At the cap: False, and one warning for the meeting."""
    counter = call_counter()
    if counter.take(kind):
        return True
    if counter.newly_capped(kind):
        limit = counter.caps.max_model_calls if kind == "model" else counter.caps.max_speech_calls
        log.warning(
            "meeting call cap reached: %d %s calls made (config/meeting.yaml); no more %s calls this meeting",
            limit,
            kind,
            kind,
        )
    return False


def resolved_fakes_refusal() -> str | None:
    """Why a real meeting must not start on what the config files RESOLVE to, or None. The file-name check in
    `guards.fakes_refusal` is only a hint (a fake behind an innocent file name passes it); this reads the roles the bot
    asks for (`meeting`, `meeting_fast`, with their fallbacks) and the speech and voice vendors."""
    fakes: list[str] = []
    try:
        config = load_config()
        for role in (BRAIN_ROLE, FAST_ROLE):
            used = profiles_used_by(config.roles[role])
            if any(config.profiles[profile_id].provider == "fake" for profile_id in used):
                fakes.append(f"role `{role}`")
        if load_speech_config(speech_file(), models_path=repo_root() / "config" / "models.yaml").vendor == "fake":
            fakes.append("the speech vendor")
        if load_voice_config(voice_file(), models_path=repo_root() / "config" / "models.yaml").vendor == "fake":
            fakes.append("the voice vendor")
    except (ProviderConfigError, KeyError) as error:
        return f"the provider config does not load ({type(error).__name__}): {error}"
    if fakes:
        return (
            f"{', '.join(fakes)} resolve to the dev fake provider (provider `fake`): a fake transcript never reaches "
            "a real meeting. Use the live config (only you set LIVE=1)."
        )
    return None


def start_up_check(*, allow_fakes: bool = False) -> None:
    """Run once when a session starts, before the bot joins anything: builds and validates the meeting's call counter
    (a bad `config/meeting.yaml` must not surface mid-meeting) and refuses the dev fakes by what the config resolves
    to. Raises `BotRefused` with a message that says what to change."""
    try:
        call_counter()
    except ProviderConfigError as error:
        raise BotRefused(f"start-up check failed, nothing was joined: {error}") from None
    if not allow_fakes:
        refusal = resolved_fakes_refusal()
        if refusal:
            raise BotRefused(f"start-up check failed, nothing was joined: {refusal}")


def load_config() -> ProvidersConfig:
    return load_providers_config(models_file(), repo_root() / "config" / "prices.yaml")


def make_router(config: ProvidersConfig | None = None, *, router: Router | None = None) -> Router:
    refusal = recording_refusal()
    if refusal:
        raise BotRefused(refusal)
    return router or Router(config or load_config(), fixtures_dir=fixtures_dir())


# -- errors ----------------------------------------------------------------------------------------------------------
def _cause(error: BaseException) -> BaseException:
    seen = 0
    while error.__cause__ is not None and seen < 5:
        error, seen = error.__cause__, seen + 1
    return error


def is_retryable(error: BaseException) -> bool:
    return isinstance(_cause(error), QuotaError | RetryableError)


def unavailable(error: BaseException) -> LLMUnavailable:
    """The bot-level error for a failed model call. Class names only: a provider message must never reach a log line."""
    cause = _cause(error)
    if isinstance(cause, QuotaError):
        return Busy("the model is rate limited (quota)")
    if isinstance(error, TokenCapExceededError):
        return LLMUnavailable("the request is over the role's input cap")
    if isinstance(cause, RequestError):
        return LLMUnavailable("the model service rejected the request or the credentials")
    return LLMUnavailable(f"the model call failed ({type(cause).__name__})")


def call_error(error: BaseException) -> ModelCallError:
    """The shape `FastLLM` reads: an HTTP-like code and a status word."""
    cause = _cause(error)
    if isinstance(cause, QuotaError):
        return ModelCallError(429, "RESOURCE_EXHAUSTED", "quota")
    if isinstance(cause, RequestError) or isinstance(error, TokenCapExceededError):
        return ModelCallError(400, "INVALID_ARGUMENT", "rejected")
    return ModelCallError(None, "", type(cause).__name__)


def _thinking(level: str | None) -> str | None:
    return None if level in (None, "", "off") else level


# -- the analysis model (sync) --------------------------------------------------------------------------------------
class ProviderLLM:
    """`brain.LLM`: `generate(system, prompt)` returns the model's raw JSON text. The router already cascades to the
    role's fallback; this adds the bot's own patience for a throttled project (backoff, then give up)."""

    def __init__(
        self,
        router: Router | None = None,
        *,
        role: str = BRAIN_ROLE,
        sleep: Callable[[float], None] = time.sleep,
        max_attempts: int = 4,
        max_output_tokens: int | None = None,
    ) -> None:
        self.router = make_router(router=router)
        self.role, self.sleep, self.max_attempts = role, sleep, max_attempts
        self.max_output_tokens = max_output_tokens

    def generate(self, system: str, prompt: str) -> str:
        request = GenerateRequest(
            prompt=prompt, system=system, json_mode=True, max_output_tokens=self.max_output_tokens
        )
        for attempt in range(1, self.max_attempts + 1):
            if not take_call("model"):
                raise LLMUnavailable("the meeting's model call cap is reached (config/meeting.yaml)")
            try:
                result = self.router.generate(self.role, request)
            except RouterError as error:
                if not is_retryable(error) or attempt == self.max_attempts:
                    raise unavailable(error) from None
                self.sleep(min(60.0, 2.0**attempt))
                continue
            if result.outcome != "ok" or result.response is None:
                raise LLMUnavailable("the model reply was blocked")
            return result.response.text or ""
        raise LLMUnavailable("the model call failed")  # unreachable


# -- the fast model (async, streaming) ------------------------------------------------------------------------------
class ProviderFastClient:
    """What `FastLLM` opens a stream on. One call runs on a worker thread (the router is synchronous) and its text
    deltas are handed back in order. There is no connection to keep warm, so `warm()` says it did nothing."""

    def __init__(self, router: Router | None = None, *, role: str = FAST_ROLE) -> None:
        self.router = make_router(router=router)
        self.role = role

    async def open(
        self, system: str, prompt: str, *, json_mode: bool, max_tokens: int, thinking: str
    ) -> AsyncIterator[str]:
        request = GenerateRequest(
            prompt=prompt,
            system=system,
            json_mode=json_mode,
            max_output_tokens=max_tokens,
            thinking_level=_thinking(thinking),
        )
        if not take_call("model"):
            raise CallCapReached("the meeting's model call cap is reached (config/meeting.yaml)")
        try:
            run = await asyncio.to_thread(self.router.stream, self.role, request)
        except RouterError as error:
            raise call_error(error) from None
        return self._deltas(iter(run))

    async def _deltas(self, chunks: Any) -> AsyncIterator[str]:
        end: Any = object()
        try:
            while True:
                try:
                    chunk = await asyncio.to_thread(next, chunks, end)
                except RouterError as error:
                    raise call_error(error) from None
                if chunk is end:
                    return
                if chunk.text:
                    yield chunk.text
        finally:
            close = getattr(chunks, "close", None)
            if close:
                close()

    async def warm(self) -> bool:
        return False


# -- speech to text (batch audio) -----------------------------------------------------------------------------------
class ProviderSpeech:
    """`SpeechProvider.transcribe` for WAV clips: segments, or one line of text."""

    def __init__(self, provider: SpeechProvider | None = None) -> None:
        if provider is None:
            config = load_speech_config(speech_file(), models_path=repo_root() / "config" / "models.yaml")
            provider = build_speech_provider(config, fixtures_dir=fixtures_dir())
        self.provider = provider

    def segments(self, wav: bytes, language: str | None = "en") -> list[dict[str, Any]]:
        if not take_call("speech"):
            raise LLMUnavailable("the meeting's speech call cap is reached (config/meeting.yaml)")
        try:
            result = self.provider.transcribe(wav, media_type=WAV_TYPE, language=language)
        except Exception as error:  # the provider's own errors carry no secrets, but the bot reports a class name only
            raise LLMUnavailable(f"speech to text failed ({type(_cause(error)).__name__})") from None
        return list(result["segments"])

    def text(self, wav: bytes, language: str | None = "en") -> str:
        return " ".join(s["text"].strip() for s in self.segments(wav, language) if s["text"].strip())


# -- the voice (text to speech) -------------------------------------------------------------------------------------
class ProviderTTS:
    """`tts.TTSProvider` on `SpeechProvider.synthesize`. The vendor, voice and sample rate are `config/voice.yaml`.
    The provider streams the reply (`synthesize_stream`): the first piece is handed on the moment the service sends it
    (a provider that cannot stream sends the whole reply as one piece), cut to the player's chunk size, and the text-in
    to first-audio latency is logged (counts only). Refusals that cannot clear within the meeting
    (no live switch, a refused request) are `permanent`, so the fallback voice takes over for the rest of it."""

    name = "provider-voice"

    def __init__(
        self,
        provider: SpeechProvider | None = None,
        config: VoiceConfig | None = None,
        clock: Callable[[], float] = time.monotonic,
        meter: LiveVoiceMeter | None = None,
    ) -> None:
        self._clock = clock
        self.config = config or load_voice_config(voice_file(), models_path=repo_root() / "config" / "models.yaml")
        # SEC-16 (BQ-M2-1): the Live voice speaks only through a spend hook this process was given (see make_tts)
        self.provider = provider or build_voice_provider(self.config, fixtures_dir=fixtures_dir(), meter=meter)
        self.sample_rate = self.config.sample_rate

    async def stream(self, text: str) -> AsyncIterator[bytes]:
        spoken = " ".join(text.split())[: self.config.max_chars]
        if not take_call("speech"):  # the fallback voice (local, no provider call) speaks for the rest of THIS meeting
            raise TTSError(
                "the meeting's speech call cap is reached (config/meeting.yaml)", permanent=True, remember=False
            )
        started, first_ms, end = self._clock(), None, object()
        pieces: Any = None
        try:
            while True:
                try:
                    if pieces is None:  # a refused request (no live switch, a bad voice) raises here, before audio
                        pieces = await asyncio.to_thread(lambda: iter(self.provider.synthesize_stream(spoken)))
                    pcm = await asyncio.to_thread(next, pieces, end)
                except Exception as error:
                    cause = _cause(error)
                    if isinstance(cause, LiveVoiceRefused):
                        # BQ-M2-12: the spend meter refused one reply. A transient word is asked again next reply;
                        # a permanent one ends the Live voice for THIS meeting only: the state file is keyed by
                        # voice, not by person or attend, so a cap or a lost claim is never written to it.
                        raise TTSError(
                            f"the voice could not speak (the spend meter refused: {cause.reason})",
                            permanent=not cause.transient,
                            remember=False,
                        ) from None
                    raise TTSError(
                        f"the voice could not speak ({type(cause).__name__})",
                        permanent=isinstance(cause, NotConfigured | RequestError),
                    ) from None
                if pcm is end:
                    return
                if first_ms is None:  # FR-MTG-11: text in to first audio out, counts only (never the text)
                    now = self._clock()
                    first_ms = (now - started) * 1000
                    stt_end = STT_END_AT.get()  # when the turn's speech-to-text result came back (bot clock), if known
                    since_stt = "" if stt_end is None else f" stt_end_to_first_audio_ms={(now - stt_end) * 1000:.0f}"
                    log.info("voice latency: characters=%d first_audio_ms=%.0f%s", len(spoken), first_ms, since_stt)
                for start in range(0, len(pcm), 4800):
                    yield pcm[start : start + 4800]
        finally:
            close = getattr(pieces, "close", None)
            if callable(close):
                close()


def make_tts(meter: LiveVoiceMeter | None = None) -> TTSProvider | None:
    """The configured voice with the local espeak voice as backup, the local voice alone if the configured one cannot be
    built, else None (the bot then stays chat-only). A bad voice config (an unknown vendor, a denied model) is not
    swallowed: it fails start-up. `meter` is the SEC-16 ledger hook of the flagged Gemini Live voice; the bot process
    has none yet (BQ-M2-4 in docs/open-questions.md), so under the live switch it speaks with Chirp, never Live."""
    local: LocalTTS | None = None
    try:
        local = LocalTTS()
    except TTSError as e:
        log.info("local voice unavailable: %s", e)
    cloud = ProviderTTS(meter=meter)
    if local is None:
        return cloud
    return FallbackTTS(cloud, local, ROOT / "out" / ".tts_state.json", f"{cloud.config.vendor}/{cloud.config.voice}")
