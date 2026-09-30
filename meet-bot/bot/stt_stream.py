"""Streaming speech-to-text over ElevenLabs Scribe v2 Realtime (WebSocket), built not to waste credits.

Audio goes out as base64 PCM (16 kHz mono s16le); partial transcripts come back while people are still talking, and
committed transcripts (with word timestamps and speaker ids) when the server's VAD hears a pause.

Credit safety (you pay per audio second sent):
- AudioGate: silence is never sent. Speech opens the gate (with a short lead-in so first words are not clipped) and it
  closes shortly after the last speech.
- The WebSocket is opened lazily on the first speech and closed after `idle_close_s` of quiet.
- The caller only feeds audio while someone who matters is in the meeting.
- `total_sent_s` counts every second actually sent, so the bill is visible.

The key comes from ELEVENLABS_API_KEY, goes only in the `xi-api-key` header, and is redacted from errors.
Protocol: https://elevenlabs.io/docs/api-reference/speech-to-text/v-1-speech-to-text-realtime
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import struct
from collections import Counter, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

from .config import STT_MODEL

log = logging.getLogger("bot.stt")
DEFAULT_URL = "wss://api.elevenlabs.io/v1/speech-to-text/realtime"
FATAL = {"auth_error", "quota_exceeded", "unaccepted_terms"}
BYTES_PER_S = 32000.0  # 16 kHz * 2 bytes


class STTUnavailable(RuntimeError):
    pass


def _rms(pcm: bytes) -> float:
    n = len(pcm) // 2
    if not n:
        return 0.0
    v = struct.unpack("<" + "h" * n, pcm[: n * 2])
    return (sum(x * x for x in v) / n) ** 0.5


class AudioGate:
    """Lets audio through only around speech: a lead-in before it, a tail after it. Frames are (pcm, start_time_s)."""

    def __init__(self, rms_on: float = 150.0, preroll_frames: int = 6, hangover_frames: int = 15) -> None:
        self.rms_on, self.hangover_frames = rms_on, hangover_frames
        self._pre: deque[tuple[bytes, float]] = deque(maxlen=preroll_frames)
        self._hang = 0

    def reset(self) -> None:
        self._pre.clear()
        self._hang = 0

    def feed(self, frame: bytes, t: float) -> list[tuple[bytes, float]]:
        if _rms(frame) >= self.rms_on:
            out = list(self._pre) + [(frame, t)] if self._hang == 0 else [(frame, t)]
            self._pre.clear()
            self._hang = self.hangover_frames
            return out
        if self._hang > 0:
            self._hang -= 1
            return [(frame, t)]
        self._pre.append((frame, t))
        return []


@dataclass
class Final:
    text: str
    start_s: float  # seconds on the session audio clock (0 = start of recording)
    end_s: float
    speaker_id: str | None = None
    words: list[dict[str, Any]] = field(default_factory=list)


def final_from_message(
    msg: dict[str, Any], base_s: float = 0.0, mapper: Callable[[float], float] | None = None
) -> Final | None:
    """A committed transcript message -> Final. `mapper` turns stream seconds into session seconds."""
    text = (msg.get("text") or "").strip()
    if not text:
        return None
    tm = mapper or (lambda s: base_s + s)
    words = [w for w in msg.get("words") or [] if w.get("type", "word") == "word"]
    if words:
        start, end = tm(float(words[0].get("start", 0.0))), tm(float(words[-1].get("end", 0.0)))
        votes = Counter(w.get("speaker_id") for w in words if w.get("speaker_id"))
        speaker = votes.most_common(1)[0][0] if votes else None
    else:
        start = end = tm(0.0)
        speaker = None
    return Final(text, round(start, 2), round(end, 2), speaker, words)


class SpeakerNames:
    """Learns which Scribe speaker id is which person, by voting with the caption speaker active at that time."""

    def __init__(self) -> None:
        self.votes: dict[str, Counter] = {}

    def resolve(self, speaker_id: str | None, caption_speaker: str | None) -> str | None:
        if speaker_id and caption_speaker:
            self.votes.setdefault(speaker_id, Counter())[caption_speaker] += 1
        if speaker_id and self.votes.get(speaker_id):
            return self.votes[speaker_id].most_common(1)[0][0]
        return caption_speaker


class ScribeStream:
    """Feed `(pcm, session_time_s)` tuples into an asyncio.Queue (None ends it); callbacks receive transcripts."""

    def __init__(
        self,
        on_partial: Callable[[str], None],
        on_final: Callable[[Final], None],
        api_key: str | None = None,
        url: str = DEFAULT_URL,
        keyterms: list[str] | None = None,
        silence_s: float = 0.6,
        idle_close_s: float = 20.0,
        connect: Callable[..., Any] | None = None,
    ) -> None:
        self.key = api_key or os.environ.get("ELEVENLABS_API_KEY", "")
        if not self.key:
            raise STTUnavailable("ELEVENLABS_API_KEY is not set. Add it to .env to use --stt elevenlabs.")
        self.on_partial, self.on_final = on_partial, on_final
        self.url, self.keyterms, self.silence_s = url, [k for k in (keyterms or []) if k][:10], silence_s
        self.idle_close_s = idle_close_s
        self._connect = connect
        self.total_sent_s = 0.0  # audio seconds sent over all connections: what you are billed for
        self.connections = 0
        self.fatal: str | None = None
        self._stop = asyncio.Event()
        self._pending: tuple[bytes, float] | None = None  # a chunk the server closed on; resend after reconnecting
        self._plain: dict[str, asyncio.TimerHandle] = {}
        self._map: list[tuple[float, float]] = [(0.0, 0.0)]  # (seconds into this connection's stream, session seconds)
        self._conn_sent_s = 0.0
        self._next_t = 0.0

    def _full_url(self, with_keyterms: bool) -> str:
        params: list[tuple[str, str]] = [
            ("model_id", STT_MODEL),
            ("audio_format", "pcm_16000"),
            ("commit_strategy", "vad"),
            ("vad_silence_threshold_secs", str(self.silence_s)),
            ("include_timestamps", "true"),
            ("language_code", "en"),
            ("enable_logging", "false"),
        ]
        if with_keyterms:
            params += [("keyterms", k) for k in self.keyterms]
        return f"{self.url}?{urlencode(params)}"

    def _to_session(self, stream_s: float) -> float:
        pos, sess = max((m for m in self._map if m[0] <= stream_s + 1e-6), key=lambda m: m[0], default=(0.0, 0.0))
        return sess + (stream_s - pos)

    async def run(self, audio_q: asyncio.Queue) -> None:
        use_terms, backoff = bool(self.keyterms), 1.0
        while self.fatal is None:
            first = self._pending
            self._pending = None
            if first is None:
                first = await self._get(audio_q)  # no connection, and no cost, until there is something to transcribe
            if first == "STOP":
                break
            if first is None:
                return
            try:
                if await self._session(audio_q, first, use_terms):
                    return
                backoff = 1.0
            except Exception as e:  # dropped connection / rejected params: retry, then give up loudly
                msg = str(e).replace(self.key, "[redacted]")
                log.warning("streaming transcription connection problem: %s", msg[:200])
                if use_terms and "keyterm" in msg.lower():
                    use_terms = False
                await asyncio.sleep(backoff)
                backoff = min(15.0, backoff * 2)
        raise STTUnavailable(self.fatal or "streaming transcription stopped")

    async def _session(self, audio_q: asyncio.Queue, first: tuple[bytes, float], use_terms: bool) -> bool:
        """One connection. True = audio ended for good; False = closed because it went quiet (or fatal)."""
        connect = self._connect
        if connect is None:
            import websockets

            connect = websockets.connect
        self.connections += 1
        self._map, self._conn_sent_s, self._next_t = [(0.0, first[1])], 0.0, first[1]
        async with connect(
            self._full_url(use_terms), additional_headers={"xi-api-key": self.key}, max_size=2**22
        ) as ws:
            log.info("streaming transcription connected (speech started)")
            recv = asyncio.create_task(self._receive(ws))
            try:
                ended = await self._send(ws, audio_q, first)
            finally:
                recv.cancel()
        if self.fatal:
            raise STTUnavailable(self.fatal)
        return ended

    async def _send(self, ws: Any, audio_q: asyncio.Queue, first: tuple[bytes, float]) -> bool:
        chunk: Any = first
        while True:
            pcm, t = chunk
            if abs(t - self._next_t) > 0.15:  # a gap in the audio (silence was skipped): remember the jump
                self._map.append((self._conn_sent_s, t))
            dur = len(pcm) / BYTES_PER_S
            self._next_t = t + dur
            self._conn_sent_s += dur
            self.total_sent_s += dur
            try:
                await ws.send(
                    json.dumps(
                        {
                            "message_type": "input_audio_chunk",
                            "audio_base_64": base64.b64encode(pcm).decode(),
                            "sample_rate": 16000,
                        }
                    )
                )
            except Exception as e:
                if type(e).__name__.startswith(
                    "ConnectionClosed"
                ):  # the server ended an idle session: reconnect at once
                    log.info("server closed the streaming session; reconnecting")
                    self._pending = (pcm, t)
                    return False
                raise
            try:
                chunk = await asyncio.wait_for(self._get(audio_q), timeout=self.idle_close_s)
            except TimeoutError:
                log.info("quiet for %.0fs: closing the streaming connection (no audio, no cost)", self.idle_close_s)
                return False
            if chunk == "STOP":
                return False
            if chunk is None:
                await ws.send(
                    json.dumps(
                        {"message_type": "input_audio_chunk", "audio_base_64": "", "commit": True, "sample_rate": 16000}
                    )
                )
                await asyncio.sleep(1.5)  # let the final commit come back
                return True

    async def _get(self, audio_q: asyncio.Queue) -> Any:
        """Next queue item, or "STOP" if the receiver hit a fatal error meanwhile."""
        getter, stopper = asyncio.ensure_future(audio_q.get()), asyncio.ensure_future(self._stop.wait())
        try:
            done, _ = await asyncio.wait({getter, stopper}, return_when=asyncio.FIRST_COMPLETED)
        except (
            asyncio.CancelledError
        ):  # a timeout above us: do not leave a reader behind that would swallow the next chunk
            for f in (getter, stopper):
                f.cancel()
            raise
        if getter in done:
            stopper.cancel()
            return getter.result()
        getter.cancel()
        return "STOP"

    def _flush_plain(self, fin: Final) -> None:
        if self._plain.pop(fin.text, None) is not None:
            self.on_final(fin)

    async def _receive(self, ws: Any) -> None:
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except (TypeError, ValueError):
                continue
            kind = msg.get("message_type")
            if kind == "partial_transcript":
                self.on_partial((msg.get("text") or "").strip())
            elif kind in ("committed_transcript_with_timestamps", "committed_transcript"):
                fin = final_from_message(msg, mapper=self._to_session)
                if fin is None:
                    continue
                if kind == "committed_transcript":
                    # Usually followed by the same commit WITH word timestamps and speaker ids, which is the one we want.
                    loop = asyncio.get_running_loop()
                    self._plain[fin.text] = loop.call_later(1.0, self._flush_plain, fin)
                else:
                    pending = self._plain.pop(fin.text, None)
                    if pending:
                        pending.cancel()
                    self.on_final(fin)
            elif kind in FATAL:
                self.fatal = f"{kind}: {msg.get('error', '')}".replace(self.key, "[redacted]")
                self._stop.set()
                log.error("streaming transcription stopped: %s", self.fatal)
                return
            elif kind and kind != "session_started":
                text = str(msg.get("error") or msg.get("message") or "").strip()
                if text:
                    log.warning("streaming transcription: %s %s", kind, text[:160])
