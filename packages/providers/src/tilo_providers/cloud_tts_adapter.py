"""tilo_providers.cloud_tts_adapter: the bot's voice on Google Cloud Text-to-Speech, a Chirp 3 HD voice by STREAMING
synthesis (FR-MTG-11, closes BQ-MTG11-2/-3; D-1 Google only). `synthesize_stream` sends the voice settings and the text
on one `StreamingSynthesize` call and hands each audio piece on as it arrives, so the bot starts speaking about a second
after the first reply text instead of after the whole reply is synthesized. The voice name (`en-US-Chirp3-HD-<Name>`),
the sample rate, the region, the caps and the request timeout are config (`config/voice.yaml`, PL-01).

Like the other Google adapters, building a REAL client needs `LIVE=1` (only the user sets it) and the shared Google
settings guard; tests inject `client=` (anything with `streaming_synthesize(requests, timeout=...)`) and never reach the
network. `google-cloud-texttospeech` is imported lazily and only for a real client, so replay, CI and the dev fake never
load it. Requests are plain mappings here; the thin SDK wrapper turns each into the SDK's request type.

Each reply logs a `VoiceTiming` (characters, chunks, bytes, request-to-first-audio and total milliseconds) and hands
it to `on_timing`: counts only, never the text, the voice or the audio. `characters` is the unit of the profile's
`character` unit_price (ADR-0029)."""

from __future__ import annotations

import importlib
import logging
import os
import re
import time
from collections.abc import Callable, Iterator
from typing import Any

from tilo_providers.errors import ProviderError, RequestError, map_http_status, map_transport_error
from tilo_providers.google_adapter import _GOOGLE_SECRET_RE, validate_google_settings
from tilo_providers.interfaces import SpeechProvider
from tilo_providers.speech import VoiceTiming, check_synth_request

log = logging.getLogger("tilo_providers.voice")
_LOCALE_RE = re.compile(
    r"([a-z]{2,3}-[A-Z]{2})-[A-Za-z0-9-]+"
)  # `en-US-Chirp3-HD-<Name>`: the locale is its first two parts
_WAV_HEADER_MAX = 128  # a RIFF header is 44 bytes; look no further than this for its `data` marker


def endpoint_for(region: str) -> str | None:
    """The regional Cloud TTS host (`<region>-texttospeech.googleapis.com`), or None for the default endpoint."""
    return None if region == "global" else f"{region}-texttospeech.googleapis.com"


def _strip_wav_header(chunk: bytes) -> bytes:
    """A streamed PCM reply may open with a WAV header (BQ-MTG11-14); the bot wants raw samples, so drop it if there."""
    if chunk[:4] != b"RIFF":
        return chunk
    marker = chunk.find(b"data", 12, _WAV_HEADER_MAX)
    return chunk[marker + 8 :] if marker >= 0 else chunk


class _SdkStreamingClient:
    """Wraps the SDK client: each request mapping becomes the SDK's `StreamingSynthesizeRequest`."""

    def __init__(self, client: Any, request_type: Any) -> None:
        self._client, self._request_type = client, request_type

    def streaming_synthesize(self, requests: Any, timeout: Any = None) -> Any:
        return self._client.streaming_synthesize((self._request_type(r) for r in requests), timeout=timeout)


class GoogleCloudTTSProvider(SpeechProvider):
    def __init__(
        self,
        *,
        voice: str,
        sample_rate: int,
        project: str,
        region: str = "global",
        client: Any | None = None,
        timeout_s: float = 15.0,
        max_chars: int | None = None,
        max_audio_bytes: int | None = None,
        clock: Callable[[], float] = time.monotonic,
        on_timing: Callable[[VoiceTiming], None] | None = None,
    ) -> None:
        self._voice, self._rate, self._timeout = voice, sample_rate, timeout_s
        self._max_chars, self._max_audio_bytes = max_chars, max_audio_bytes
        self._clock, self._on_timing = clock, on_timing
        self.last_timing: VoiceTiming | None = None
        if client is None:
            if os.environ.get("LIVE") != "1":  # EFF-01: reachable directly, not only through the voice wrapper
                raise ProviderError("EFF-01: refusing to build a real network client without LIVE=1 (inject client=)")
            validate_google_settings(project, region)  # before any client exists
            client = self._build_client(project, region)
        self._client = client

    @staticmethod
    def _build_client(project: str, region: str) -> Any:
        sdk = importlib.import_module("google.cloud.texttospeech")
        options: dict[str, Any] = {"quota_project_id": project}
        endpoint = endpoint_for(region)
        if endpoint:
            options["api_endpoint"] = endpoint
        return _SdkStreamingClient(sdk.TextToSpeechClient(client_options=options), sdk.StreamingSynthesizeRequest)

    def redact(self, text: str) -> str:
        return _GOOGLE_SECRET_RE.sub("[redacted]", text)

    def transcribe(self, audio: bytes, **kwargs: Any) -> Any:
        raise RequestError("FR-MTG-11: the Cloud TTS voice only synthesizes; transcribe through the speech provider")

    def synthesize(self, text: str, *, voice: str | None = None, **kwargs: Any) -> bytes:
        return b"".join(self.synthesize_stream(text, voice=voice, **kwargs))

    def synthesize_stream(self, text: str, *, voice: str | None = None, **kwargs: Any) -> Iterator[bytes]:
        """Validates now (nothing is sent for a bad call), then returns the lazy stream of even-length PCM pieces."""
        text, voice = check_synth_request(text, voice, kwargs, self._max_chars)
        name = voice or self._voice
        match = _LOCALE_RE.fullmatch(name)
        if match is None:
            raise RequestError("FR-MTG-11: the Cloud TTS voice must look like en-US-Chirp3-HD-<Name>")
        requests: list[dict[str, Any]] = [
            {
                "streaming_config": {
                    "voice": {"name": name, "language_code": match.group(1)},
                    "streaming_audio_config": {"audio_encoding": "PCM", "sample_rate_hertz": self._rate},
                }
            },
            {"input": {"text": text}},
        ]
        return self._stream(requests, len(text), self._clock())

    def _stream(self, requests: list[dict[str, Any]], characters: int, started: float) -> Iterator[bytes]:
        chunks = total = 0
        first_ms: float | None = None
        carry = b""
        responses: Any = None
        try:
            try:
                responses = self._client.streaming_synthesize(iter(requests), timeout=self._timeout)
                for response in responses:
                    data = getattr(response, "audio_content", None)
                    if not isinstance(data, bytes | bytearray):
                        continue
                    data = bytes(data)
                    if chunks == 0 and not carry:
                        data = _strip_wav_header(data)
                    data = carry + data
                    carry = data[-1:] if len(data) % 2 else b""
                    data = data[: len(data) - len(carry)]
                    if not data:
                        continue
                    if self._max_audio_bytes is not None and total + len(data) > self._max_audio_bytes:
                        raise ProviderError(f"EFF-03: the voice audio is over the cap of {self._max_audio_bytes} bytes")
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
            close = getattr(responses, "close", None)
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
        if type(code) is int and 400 <= code <= 599:  # google.api_core errors carry the HTTP status in `code`
            return map_http_status(code, self.redact(str(getattr(error, "message", ""))))
        if isinstance(error, TimeoutError):
            return map_http_status(504, "PL-02: the voice request timed out")
        return map_transport_error(error) or ProviderError(f"FR-MTG-11: the voice call failed ({type(error).__name__})")
