"""The bot's voice: turn-taking, microphone control, playback and barge-in, behind a small interface.

    Speaker.say(text) -> SpeakResult      never raises; failure just means the chat message is the only output
    Speaker.stop()                        cut off whatever is being said

How a spoken reply goes:
  1. wait for a natural pause (nobody talking for `pause_s`), give up after `max_wait_s`
  2. unmute the bot's Meet microphone while the TTS request is already in flight
  3. stream the audio into the virtual microphone; if a human talks over it for `barge_in_s`, stop at once
  4. mute again shortly after the last sound
The provider (TTSProvider), the microphone switch (MicControl) and the voice-activity source (Activity) are all injected,
so each can be replaced or faked in tests.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from .tts import TTSError, TTSProvider

log = logging.getLogger("bot.speaker")


class MicControl(Protocol):
    async def set(self, on: bool) -> bool: ...


class Activity(Protocol):
    def speaking_within(self, window_s: float) -> bool: ...
    def loud_run_s(self) -> float: ...


@dataclass
class SpeakResult:
    spoken: bool
    interrupted: bool = False
    error: str | None = None
    waited_s: float = 0.0
    first_audio_s: float | None = None  # from the start of say() to the first audio chunk from the provider
    total_s: float = 0.0


class Speaker(Protocol):
    async def say(self, text: str) -> SpeakResult: ...
    async def stop(self) -> None: ...


class NullSpeaker:
    """Chat-only mode."""

    async def say(self, text: str) -> SpeakResult:
        return SpeakResult(False, error="voice replies are off")

    async def stop(self) -> None:
        return None


async def _prepend(first: bytes, rest: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
    yield first
    async for c in rest:
        yield c


class VoiceSpeaker:
    def __init__(
        self,
        tts: TTSProvider,
        player: Any,
        mic: MicControl,
        activity: Activity | None = None,
        pause_s: float = 0.6,
        max_wait_s: float = 5.0,
        barge_in_s: float = 0.5,
        tail_s: float = 0.4,
        sleep: Callable[[float], Any] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.tts, self.player, self.mic, self.activity = tts, player, mic, activity
        self.pause_s, self.max_wait_s, self.barge_in_s, self.tail_s = pause_s, max_wait_s, barge_in_s, tail_s
        self._sleep, self._clock = sleep, clock
        self._lock = asyncio.Lock()  # one thing said at a time; the next reply waits its turn
        self._stop = False

    async def stop(self) -> None:
        self._stop = True

    async def _wait_for_pause(self) -> float | None:
        """Seconds waited, or None if people never stopped talking."""
        if self.activity is None:
            return 0.0
        start = self._clock()
        while self.activity.speaking_within(self.pause_s):
            if self._clock() - start >= self.max_wait_s:
                return None
            await self._sleep(0.1)
        return self._clock() - start

    def _human_took_over(self) -> bool:
        return self._stop or (self.activity is not None and self.activity.loud_run_s() >= self.barge_in_s)

    async def say(self, text: str) -> SpeakResult:
        t0 = self._clock()
        async with self._lock:
            self._stop = False
            waited = await self._wait_for_pause()
            if waited is None:
                return SpeakResult(False, error="people kept talking, so I stayed quiet", total_s=self._clock() - t0)
            unmute = asyncio.create_task(self.mic.set(True))
            first_audio = None
            try:
                stream = self.tts.stream(text)
                try:
                    first = await stream.__anext__()
                except StopAsyncIteration:
                    raise TTSError("the voice service returned no audio") from None
                first_audio = self._clock() - t0
                if not await unmute:
                    raise TTSError("could not unmute the Meet microphone")
                done = await self.player.play(_prepend(first, stream), self.tts.sample_rate, self._human_took_over)
                return SpeakResult(
                    True, interrupted=not done, waited_s=waited, first_audio_s=first_audio, total_s=self._clock() - t0
                )
            except TTSError as e:
                return SpeakResult(
                    False, error=str(e), waited_s=waited, first_audio_s=first_audio, total_s=self._clock() - t0
                )
            except Exception as e:  # never let a voice problem break the meeting
                log.warning("speaking failed: %s", e)
                return SpeakResult(
                    False, error=f"{type(e).__name__}: {e}"[:160], waited_s=waited, total_s=self._clock() - t0
                )
            finally:
                if not unmute.done():
                    unmute.cancel()
                await self._sleep(self.tail_s)
                try:
                    await self.mic.set(False)
                except Exception as e:
                    log.warning("could not re-mute the microphone: %s", e)
