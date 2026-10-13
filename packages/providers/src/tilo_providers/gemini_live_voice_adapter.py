"""tilo_providers.gemini_live_voice_adapter: Gemini Live as the bot's voice (FR-MTG-11, M2), an OPTIONAL alternative to
the Chirp 3 HD voice. It implements the same `SpeechProvider` as `cloud_tts_adapter` (`synthesize_stream` of even-length
24 kHz PCM pieces, `VoiceTiming`, the same caps) and is selected only by `voice.live.enabled` in `config/voice.yaml`,
which ships off: Chirp stays the voice (`voice.build_voice_provider`). Model, voice, caps and location are config
(PL-01); the system instruction is `prompts/speech/live_read_aloud.md`.

Three ways to get audio, none of them silent:
- an injected `session_factory` (tests, a fake session; never the network);
- no live switch: REPLAY of hand-written recordings `<fixtures_dir>/voice-live-recordings/<key>.json`, keyed by profile,
  model, voice and the SHA-256 of the text (a recording stores the digest, never the words). A miss is `NotConfigured`,
  never a fall-through to a live call, so the bot falls back to its local voice;
- `LIVE=1` (only the user sets it), `voice.live.price_approved` (PL-06: a current Live quote the user approved) and
  `GOOGLE_CLOUD_PROJECT`: one Live session per reply on the user's ADC, `google.genai` imported lazily.
Nothing is recorded: audio of a meeting reply is not kept."""

from __future__ import annotations

import asyncio
import base64
import functools
import hashlib
import json
import logging
import os
import time
from collections.abc import AsyncGenerator, Callable, Iterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tilo_providers.errors import NotConfigured, ProviderError, RequestError, map_http_status, map_transport_error
from tilo_providers.google_adapter import _GOOGLE_SECRET_RE, validate_google_settings
from tilo_providers.interfaces import SpeechProvider
from tilo_providers.prompts import load_prompt
from tilo_providers.replay import is_live_mode
from tilo_providers.speech import VoiceTiming, check_synth_request
from tilo_providers.voice import VoiceConfig

log = logging.getLogger("tilo_providers.voice")
RECORDINGS_DIR = "voice-live-recordings"
_USAGE_FIELDS = ("prompt_token_count", "response_token_count", "total_token_count")


@dataclass(frozen=True)
class LiveSessionSettings:
    """What one Live session is opened with: all of it from config or the prompt template, never from the meeting."""

    model: str
    voice: str
    system_instruction: str
    max_output_tokens: int
    location: str


SessionFactory = Callable[[LiveSessionSettings], AbstractAsyncContextManager[Any]]


def recording_key(profile_id: str, model: str, voice: str, text: str) -> str:
    """The recording's filename stem: a stable hash of (profile, model, voice, SHA-256 of the text)."""
    request = {
        "profile": profile_id,
        "model": model,
        "voice": voice,
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }
    return hashlib.sha256(json.dumps(request, sort_keys=True).encode("utf-8")).hexdigest()[:16]


@asynccontextmanager
async def _google_session(project: str, settings: LiveSessionSettings):
    from google import genai  # noqa: PLC0415  (replay, CI and the dev fake never import or construct the SDK client)
    from google.genai import types  # noqa: PLC0415

    client = genai.Client(
        vertexai=True, project=project, location=settings.location, http_options={"api_version": "v1beta1"}
    )
    try:
        voice = types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=settings.voice))
        config = types.LiveConnectConfig(
            response_modalities=[types.Modality.AUDIO],
            speech_config=types.SpeechConfig(voice_config=voice),
            max_output_tokens=settings.max_output_tokens,
            system_instruction=settings.system_instruction,
        )
        async with client.aio.live.connect(model=settings.model, config=config) as session:
            yield session
    finally:
        await client.aio.aclose()


class GeminiLiveVoiceProvider(SpeechProvider):
    def __init__(
        self,
        config: VoiceConfig,
        *,
        fixtures_dir: Path | str | None = None,
        session_factory: SessionFactory | None = None,
        clock: Callable[[], float] = time.monotonic,
        on_timing: Callable[[VoiceTiming], None] | None = None,
    ) -> None:
        if config.live is None or not config.live.enabled:
            raise NotConfigured("FR-MTG-11: the Gemini Live voice is off (voice.live.enabled); Chirp is the voice")
        self._config, self._live = config, config.live
        self._dir = Path(fixtures_dir) / RECORDINGS_DIR if fixtures_dir is not None else None
        self._factory, self._clock, self._on_timing = session_factory, clock, on_timing
        self.last_timing: VoiceTiming | None = None
        self.last_usage: dict[str, int] = {}

    def redact(self, text: str) -> str:
        return _GOOGLE_SECRET_RE.sub("[redacted]", text)

    def transcribe(self, audio: bytes, **kwargs: Any) -> Any:
        raise RequestError("FR-MTG-11: the Live voice only synthesizes; transcribe through the speech provider")

    def synthesize(self, text: str, *, voice: str | None = None, **kwargs: Any) -> bytes:
        return b"".join(self.synthesize_stream(text, voice=voice, **kwargs))

    def synthesize_stream(self, text: str, *, voice: str | None = None, **kwargs: Any) -> Iterator[bytes]:
        """Validates and chooses the source now (nothing is sent for a bad call, a miss or an unapproved live call),
        then returns the lazy stream of even-length PCM pieces."""
        text, voice = check_synth_request(text, voice, kwargs, self._config.max_chars)
        name, started = voice or self._live.voice, self._clock()
        source: Iterator[bytes]
        if self._factory is not None:
            source = self._turn(self._factory, text, name)
        elif is_live_mode():
            source = self._turn(self._google_factory(), text, name)
        else:
            source = self._replay(text, name)
        return self._stream(source, len(text), started)

    # -- the three sources ----------------------------------------------------------------------------------------
    def _replay(self, text: str, voice: str) -> Iterator[bytes]:
        key = recording_key(self._live.profile_id, self._live.model, voice, text)
        if self._dir is None:
            raise NotConfigured("FR-MTG-11: no recording folder; the Live voice speaks only from recordings here")
        try:
            data = json.loads((self._dir / f"{key}.json").read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise NotConfigured(
                f"FR-MTG-11: no recording {key} for this reply; replay serves recordings only"
            ) from None
        except (OSError, ValueError):
            raise ProviderError("FR-MTG-11: the Live voice recording could not be read") from None
        chunks = data.get("chunks_b64") if isinstance(data, dict) else None
        expected = (key, self._live.profile_id, self._live.model, voice, self._config.sample_rate)
        shape = (data.get("key"), data.get("profile"), data.get("model"), data.get("voice"), data.get("sample_rate"))
        if (
            not isinstance(chunks, list)
            or not chunks
            or data.get("v") != "1.0"
            or shape != expected
            or data.get("text_sha256") != hashlib.sha256(text.encode("utf-8")).hexdigest()
        ):
            raise ProviderError("FR-MTG-11: the Live voice recording does not match this request")
        try:
            return iter([base64.b64decode(c, validate=True) for c in chunks if isinstance(c, str)])
        except ValueError:
            raise ProviderError("FR-MTG-11: the Live voice recording is not valid audio") from None

    def _google_factory(self) -> SessionFactory:
        if not self._live.price_approved:  # a live call the meter has no approved price for is a silent overspend
            raise NotConfigured(
                "PL-06: the Live voice needs an approved current price quote (voice.live.price_approved)"
            )
        project = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
        if not project:
            raise NotConfigured("FR-MTG-11: GOOGLE_CLOUD_PROJECT is not set; cannot speak live")
        validate_google_settings(project, self._live.location)  # before any client exists
        return functools.partial(_google_session, project)

    def _turn(self, factory: SessionFactory, text: str, voice: str) -> Iterator[bytes]:
        """One reply on one Live session, driven from sync code on a private event loop (the voice is sync, the SDK
        is async). The deadline is for the whole reply; closing the iterator closes the session."""
        settings = LiveSessionSettings(
            self._live.model,
            voice,
            load_prompt("speech", "live_read_aloud.md"),
            self._live.max_output_tokens,
            self._live.location,
        )
        loop, pieces = asyncio.new_event_loop(), self._receive(factory, settings, text)
        deadline = self._clock() + self._live.timeout_s
        try:
            while True:
                budget = max(deadline - self._clock(), 0.001)
                try:
                    piece = loop.run_until_complete(asyncio.wait_for(pieces.__anext__(), budget))
                except StopAsyncIteration:
                    return
                except TimeoutError:
                    raise ProviderError("PL-02: the Live voice turn timed out") from None
                yield piece
        finally:
            try:
                loop.run_until_complete(pieces.aclose())
            finally:
                loop.close()

    async def _receive(
        self, factory: SessionFactory, settings: LiveSessionSettings, text: str
    ) -> AsyncGenerator[bytes, None]:
        mime, complete = f"audio/pcm;rate={self._config.sample_rate}", False
        async with factory(settings) as session:
            await session.send_client_content(turns={"role": "user", "parts": [{"text": text}]}, turn_complete=True)
            async for reply in session.receive():
                usage = getattr(reply, "usage_metadata", None)
                if usage is not None:  # whole numbers only: the meter reads these, never the content
                    counts = {name: getattr(usage, name, None) for name in _USAGE_FIELDS}
                    self.last_usage = {k: n for k, n in counts.items() if type(n) is int and n >= 0}
                content = getattr(reply, "server_content", None)
                if content is None:
                    continue
                if getattr(content, "interrupted", False):
                    raise ProviderError("PL-02: the Live voice turn was interrupted")
                for part in getattr(getattr(content, "model_turn", None), "parts", None) or []:
                    inline = getattr(part, "inline_data", None)
                    data = getattr(inline, "data", None)
                    if isinstance(data, bytes | bytearray) and data:
                        if getattr(inline, "mime_type", "") != mime:
                            raise ProviderError("PL-02: the Live voice sent audio in an unexpected format")
                        yield bytes(data)
                if getattr(content, "turn_complete", False):
                    complete = True
                    break
        if not complete:
            raise ProviderError("PL-02: the Live voice turn did not finish")

    # -- caps, timing and errors (the same rules as the Chirp adapter) ----------------------------------------------
    def _stream(self, source: Iterator[bytes], characters: int, started: float) -> Iterator[bytes]:
        chunks = total = 0
        first_ms: float | None = None
        carry = b""
        try:
            try:
                for data in source:
                    data = carry + data
                    carry = data[-1:] if len(data) % 2 else b""
                    data = data[: len(data) - len(carry)]
                    if not data:
                        continue
                    if total + len(data) > self._config.max_audio_bytes:
                        raise ProviderError(
                            f"EFF-03: the voice audio is over the cap of {self._config.max_audio_bytes} bytes"
                        )
                    if first_ms is None:
                        first_ms = (self._clock() - started) * 1000
                    chunks, total = chunks + 1, total + len(data)
                    yield data
            except ProviderError:
                raise
            except Exception as error:
                failure: ProviderError | None = self._failure(error)
            else:
                failure = None
            if failure is not None:
                raise failure  # built outside the except: the raw SDK error (it can echo a token) is not the cause
            if carry:
                raise ProviderError("FR-MTG-11: the voice returned an odd number of PCM bytes")
            if chunks == 0:
                raise ProviderError("FR-MTG-11: the voice returned no audio")
        finally:
            close = getattr(source, "close", None)
            if callable(close):
                close()
            self._report(VoiceTiming(characters, chunks, total, first_ms, (self._clock() - started) * 1000))

    def _report(self, timing: VoiceTiming) -> None:
        self.last_timing = timing
        first = "none" if timing.first_audio_ms is None else f"{timing.first_audio_ms:.0f}"
        log.info(
            "voice turn: characters=%d chunks=%d audio_bytes=%d first_audio_ms=%s total_ms=%.0f",
            timing.characters,
            timing.chunks,
            timing.audio_bytes,
            first,
            timing.total_ms,
        )
        if self._on_timing is not None:
            try:
                self._on_timing(timing)
            except Exception as error:  # a metering hook must never break the voice
                log.warning("voice timing hook failed (%s)", type(error).__name__)

    def _failure(self, error: Exception) -> ProviderError:
        code = getattr(error, "code", None)
        if type(code) is int and 400 <= code <= 599:  # google.genai errors carry the HTTP status in `code`
            return map_http_status(code, self.redact(str(getattr(error, "message", ""))))
        return map_transport_error(error) or ProviderError(
            f"FR-MTG-11: the Live voice call failed ({type(error).__name__})"
        )
