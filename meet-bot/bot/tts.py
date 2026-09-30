"""Text-to-speech providers behind one interface, so the voice can be swapped without touching the bot.

    provider.sample_rate  -> Hz of the PCM it yields (16-bit mono little-endian)
    provider.stream(text) -> async iterator of PCM chunks, first chunk as early as the service allows

Providers:
- ElevenLabsTTS: streaming HTTP endpoint, low-latency Flash model. Key from ELEVENLABS_API_KEY (header only, never logged).
- LocalTTS: espeak-ng in the container. Robotic, but free, offline and instant; the fallback and the test voice.
Future providers (Gemini/Google Cloud TTS, a realtime speech-to-speech API) only need to implement the same two members.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import shutil
import wave
from collections.abc import AsyncIterator
from typing import Any, Protocol

from .config import DEFAULT_TTS_MODEL

log = logging.getLogger("bot.tts")
DEFAULT_VOICE = "21m00Tcm4TlvDq8ikWAM"  # a premade ElevenLabs voice ("Rachel"); override with ELEVENLABS_VOICE_ID
MAX_CHARS = 400


class TTSError(RuntimeError):
    """Speech could not be produced. The message is safe to show; the chat message is the fallback."""


class TTSProvider(Protocol):
    name: str
    sample_rate: int

    def stream(self, text: str) -> AsyncIterator[bytes]: ...


def _clean(text: str) -> str:
    return " ".join(text.split())[:MAX_CHARS]


class ElevenLabsTTS:
    name = "elevenlabs"
    sample_rate = 24000

    def __init__(
        self,
        api_key: str | None = None,
        voice_id: str | None = None,
        model: str | None = None,
        base_url: str = "https://api.elevenlabs.io",
        client: Any = None,
    ) -> None:
        self.key = api_key or os.environ.get("ELEVENLABS_API_KEY", "")
        if not self.key:
            raise TTSError("ELEVENLABS_API_KEY is not set")
        self.voice = voice_id or os.environ.get("ELEVENLABS_VOICE_ID", "") or DEFAULT_VOICE
        self.model = model or os.environ.get("ELEVENLABS_TTS_MODEL", "") or DEFAULT_TTS_MODEL
        self.base_url = base_url.rstrip("/")
        self._client = client

    def _http(self) -> Any:
        if self._client is None:
            import httpx

            self._client = httpx.AsyncClient(timeout=httpx.Timeout(15.0, read=30.0))  # kept alive: faster next reply
        return self._client

    async def stream(self, text: str) -> AsyncIterator[bytes]:
        url = f"{self.base_url}/v1/text-to-speech/{self.voice}/stream"
        body = {
            "text": _clean(text),
            "model_id": self.model,
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75, "speed": 1.05},
        }
        try:
            async with self._http().stream(
                "POST", url, params={"output_format": "pcm_24000"}, json=body, headers={"xi-api-key": self.key}
            ) as r:
                if r.status_code != 200:
                    detail = (await r.aread()).decode("utf-8", "replace")[:200].replace(self.key, "[redacted]")
                    raise TTSError(self._explain(r.status_code, detail))
                async for chunk in r.aiter_bytes(4800):
                    if chunk:
                        yield chunk
        except TTSError:
            raise
        except Exception as e:  # network trouble
            raise TTSError(f"could not reach ElevenLabs ({type(e).__name__})") from None

    @staticmethod
    def _explain(status: int, detail: str) -> str:
        if status == 401:
            return "ElevenLabs rejected the API key"
        if status in (402, 403):
            return (
                "ElevenLabs refused text-to-speech: give the key 'Text to Speech: Access' or check your plan/credits "
                f"({detail[:100]})"
            )
        if status == 429:
            return "ElevenLabs rate/concurrency limit reached"
        if status == 422:
            return f"ElevenLabs rejected the request (voice or model id?): {detail[:120]}"
        return f"ElevenLabs error {status}: {detail[:120]}"


class LocalTTS:
    name = "local-espeak"
    sample_rate = 22050

    def __init__(self, voice: str = "en-us", words_per_minute: int = 165) -> None:
        if not shutil.which("espeak-ng"):
            raise TTSError("espeak-ng is not installed")
        self.voice, self.wpm = voice, words_per_minute

    async def stream(self, text: str) -> AsyncIterator[bytes]:
        proc = await asyncio.create_subprocess_exec(
            "espeak-ng",
            "--stdout",
            "-v",
            self.voice,
            "-s",
            str(self.wpm),
            "--",
            _clean(text),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        data, _ = await proc.communicate()
        if proc.returncode != 0 or not data:
            raise TTSError("espeak-ng produced no audio")
        with wave.open(io.BytesIO(data)) as w:
            self.sample_rate = w.getframerate()
            pcm = w.readframes(w.getnframes())
        for i in range(0, len(pcm), 4096):
            yield pcm[i : i + 4096]


class FallbackTTS:
    """Try the primary voice; if it cannot speak (plan/permission/network), use the backup so the bot is never mute.

    A plan or key problem is remembered for the rest of the meeting (no repeated failing calls); a network blip is retried.
    """

    def __init__(self, primary: TTSProvider, backup: TTSProvider) -> None:
        self.primary, self.backup = primary, backup
        self.name = primary.name
        self.sample_rate = primary.sample_rate
        self._primary_dead = False

    async def stream(self, text: str) -> AsyncIterator[bytes]:
        if not self._primary_dead:
            gen = self.primary.stream(text)
            try:
                first = await gen.__anext__()
            except TTSError as e:
                permanent = any(k in str(e) for k in ("API key", "Text to Speech", "plan", "voice or model"))
                log.warning(
                    "primary voice failed (%s); using the backup voice%s",
                    e,
                    " for the rest of this meeting" if permanent else " this time",
                )
                self._primary_dead = permanent
            except StopAsyncIteration:
                pass
            else:
                self.name, self.sample_rate = self.primary.name, self.primary.sample_rate
                yield first
                async for chunk in gen:
                    yield chunk
                return
        gen = self.backup.stream(text)
        first = await gen.__anext__()  # sets the backup's real sample rate
        self.name, self.sample_rate = self.backup.name, self.backup.sample_rate
        yield first
        async for chunk in gen:
            yield chunk


def make_tts() -> TTSProvider | None:
    """ElevenLabs if a key is configured (with the local voice as automatic backup), else the local voice, else None."""
    local: LocalTTS | None = None
    try:
        local = LocalTTS()
    except TTSError as e:
        log.info("local voice unavailable: %s", e)
    try:
        eleven = ElevenLabsTTS()
    except TTSError as e:
        log.info("ElevenLabs voice unavailable: %s", e)
        return local
    return FallbackTTS(eleven, local) if local else eleven
