"""Text-to-speech providers behind one interface, so the voice can be swapped without touching the bot.

    provider.sample_rate  -> Hz of the PCM it yields (16-bit mono little-endian)
    provider.stream(text) -> async iterator of PCM chunks, first chunk as early as the service allows

Providers:
- LocalTTS: espeak-ng in the container. Robotic, but free, offline and instant; the fallback and the test voice.
The cloud voice (FR-MTG-11) is `providers.ProviderTTS`, which implements the same two members; `providers.make_tts`
builds it with the local voice as backup.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import shutil
import time
import wave
from collections.abc import AsyncIterator
from contextvars import ContextVar
from pathlib import Path
from typing import Protocol

log = logging.getLogger("bot.tts")
MAX_CHARS = 400
# FR-MTG-11: the bot-clock time (time.monotonic) at which the speech-to-text final result for the turn being answered
# came back, or None (typed chat, no turn). The session sets it around the speak task (a task copies the context when
# it is created), so the voice can log STT end -> first audio without a signature change on every provider.
STT_END_AT: ContextVar[float | None] = ContextVar("stt_end_at", default=None)


class TTSError(RuntimeError):
    """Speech could not be produced. The message is safe to show; the chat message is the fallback.

    `permanent` marks a refusal that will not clear within the meeting (a voice the plan or key may not use): the
    fallback voice then speaks for the rest of the meeting and the refusal is remembered for a day. `remember=False`
    keeps it to this meeting (in memory only): the per-meeting call cap is not a fact about the plan or key."""

    def __init__(self, message: str, *, permanent: bool = False, remember: bool = True) -> None:
        super().__init__(message)
        self.permanent = permanent
        self.remember = remember


class TTSProvider(Protocol):
    name: str
    sample_rate: int

    def stream(self, text: str) -> AsyncIterator[bytes]: ...


def _clean(text: str) -> str:
    return " ".join(text.split())[:MAX_CHARS]


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

    def __init__(
        self, primary: TTSProvider, backup: TTSProvider, state_path: Path | None = None, voice_key: str = ""
    ) -> None:
        self.primary, self.backup = primary, backup
        self.name = primary.name
        self.sample_rate = primary.sample_rate
        self._state, self._voice_key = state_path, voice_key
        self._primary_dead = self._remembered_dead()

    def _remembered_dead(self) -> bool:
        """A voice the plan refused is not retried for a day: the failing first call otherwise delays the first reply."""
        try:
            data = json.loads(self._state.read_text(encoding="utf-8")) if self._state else {}
        except (OSError, ValueError):
            return False
        dead = data.get("voice") == self._voice_key and time.time() - data.get("at", 0) < 86400
        if dead:
            log.info("the primary voice was refused earlier (%s): using the backup voice", data.get("reason", "plan"))
        return dead

    def _remember_dead(self, reason: str) -> None:
        if self._state:
            try:
                self._state.parent.mkdir(parents=True, exist_ok=True)
                self._state.write_text(
                    json.dumps({"voice": self._voice_key, "at": time.time(), "reason": reason[:120]}), encoding="utf-8"
                )
            except OSError:
                pass

    async def stream(self, text: str) -> AsyncIterator[bytes]:
        if not self._primary_dead:
            gen = self.primary.stream(text)
            try:
                first = await gen.__anext__()
            except TTSError as e:
                permanent = e.permanent
                log.warning(
                    "primary voice failed (%s); using the backup voice%s",
                    e,
                    " for the rest of this meeting" if permanent else " this time",
                )
                self._primary_dead = permanent
                if permanent and e.remember:
                    self._remember_dead(str(e))
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
