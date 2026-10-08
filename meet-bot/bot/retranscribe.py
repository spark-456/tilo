"""Second opinion on a meeting: transcribe the recorded audio with the speech provider and compare with Meet's live captions.

Runs after the meeting (inside the container, through `bot/providers.py`). Silent stretches are skipped. The result is
out/<run>/transcript_audio.md, which you can read next to transcript.jsonl and listen to in playback.html.
The audio goes to the speech provider only (see README data note).
"""

from __future__ import annotations

import io
import logging
import struct
import time
import wave
from collections.abc import Callable
from pathlib import Path
from typing import Any

log = logging.getLogger("bot.retranscribe")


def speech_segments(
    path: Path, window_s: int = 1, rms_min: float = 40.0, join_gap_s: int = 4, pad_s: float = 1.5, max_len_s: int = 90
) -> list[tuple[float, bytes]]:
    """Cut the recording into stretches that contain sound: [(start_seconds, wav_bytes)].

    Long digital silence (waiting for people to join) is dropped, and no segment exceeds `max_len_s`, which keeps each
    model call short and accurate.
    """
    with wave.open(str(path), "rb") as w:
        rate, width, ch = w.getframerate(), w.getsampwidth(), w.getnchannels()
        total = w.getnframes() // rate
        active = []
        for sec in range(0, total, window_s):
            w.setpos(sec * rate)
            fr = w.readframes(rate * window_s)
            n = len(fr) // 2
            if n and width == 2:
                v = struct.unpack("<" + "h" * n, fr[: n * 2])
                active.append((sum(x * x for x in v) / n) ** 0.5 >= rms_min)
            else:
                active.append(False)
        spans: list[list[float]] = []
        for k, on in enumerate(active):
            if not on:
                continue
            t = k * window_s
            if spans and t - spans[-1][1] <= join_gap_s:
                spans[-1][1] = t + window_s
            else:
                spans.append([t, t + window_s])
        out: list[tuple[float, bytes]] = []
        for a, b in spans:
            a, b = max(0.0, a - pad_s), min(float(total), b + pad_s)
            while a < b:
                end = min(b, a + max_len_s)
                w.setpos(int(a * rate))
                frames = w.readframes(int((end - a) * rate))
                buf = io.BytesIO()
                with wave.open(buf, "wb") as o:
                    o.setnchannels(ch)
                    o.setsampwidth(width)
                    o.setframerate(rate)
                    o.writeframes(frames)
                out.append((a, buf.getvalue()))
                a = end
        return out


def _stamp(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 60:02d}:{total % 60:02d}"


def retranscribe(run_dir: Path, transcribe: Callable[[bytes], list[dict[str, Any]]]) -> Path:
    """`transcribe(wav_bytes)` is `ProviderSpeech.segments`: [{speaker, start_ms, text}] for one clip."""
    wav = run_dir / "audio.wav"
    if not wav.is_file():
        raise FileNotFoundError(f"{wav} not found: run the meeting with --record-audio")
    parts = []
    segments = speech_segments(wav)
    log.info("%d speech segment(s) found", len(segments))
    for offset, data in segments:
        label = _stamp(offset)
        log.info("transcribing segment at %s (%.1f MB)...", label, len(data) / 1e6)
        started = time.monotonic()
        lines = [
            f"[{_stamp(offset + seg['start_ms'] / 1000)}] {seg['speaker']}: {seg['text'].strip()}"
            for seg in transcribe(data)
            if seg["text"].strip()
        ]
        log.info("  done in %.1fs", time.monotonic() - started)
        parts.append(f"## From {label}\n\n" + ("\n".join(lines) if lines else "(no speech)") + "\n")
    if not parts:
        parts.append("(no sound found in the recording)\n")
    out = run_dir / "transcript_audio.md"
    out.write_text(
        "# Transcript from the recorded audio (speech provider)\n\nTimestamps are from the start of audio.wav, "
        "the same clock as playback.html.\n\n" + "\n".join(parts),
        encoding="utf-8",
    )
    return out
