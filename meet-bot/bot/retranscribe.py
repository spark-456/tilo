"""Second opinion on a meeting: transcribe the recorded audio with Gemini and compare with Meet's live captions.

Runs after the meeting (inside the container, needs GEMINI_API_KEY). Silent stretches are skipped. The result is
out/<run>/transcript_audio.md, which you can read next to transcript.jsonl and listen to in playback.html.
The audio goes to Gemini only (see README data note).
"""

from __future__ import annotations

import io
import logging
import re
import struct
import time
import wave
from pathlib import Path
from typing import Any

log = logging.getLogger("bot.retranscribe")

PROMPT = """Transcribe this meeting audio verbatim, in English. Label distinct speakers Speaker 1, Speaker 2, ... consistently. \
Start every utterance on its own line as: [mm:ss] Speaker N: text  (exactly the [mm:ss] format; mm:ss counts from the start of THIS clip). \
When people talk over each other, transcribe both and add (overlap). Use [unclear] for words you cannot make out. \
Do not summarise, correct, or add anything. If there is no speech, reply exactly: (no speech)."""


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


def shift_timestamps(text: str, offset_s: int) -> str:
    def fix(m: re.Match) -> str:
        total = int(m.group(1)) * 60 + int(m.group(2)) + offset_s
        return f"[{total // 60:02d}:{total % 60:02d}]"

    text = re.sub(
        r"\[\s*(\d+)m(\d+)s\d*ms\s*\]", lambda m: f"[{m.group(1)}:{int(m.group(2)):02d}]", text
    )  # "[ 0m6s444ms ]"
    return re.sub(r"\[(\d{1,2}):(\d{2})\]", fix, text)


def retranscribe(run_dir: Path, client: Any, model: str) -> Path:
    from google.genai import types

    wav = run_dir / "audio.wav"
    if not wav.is_file():
        raise FileNotFoundError(f"{wav} not found: run the meeting with --record-audio")
    parts = []
    segments = speech_segments(wav)
    log.info("%d speech segment(s) found", len(segments))
    for offset, data in segments:
        label = f"{int(offset) // 60:02d}:{int(offset) % 60:02d}"
        log.info("transcribing segment at %s (%.1f MB)...", label, len(data) / 1e6)
        started = time.monotonic()
        resp = client.models.generate_content(
            model=model,
            contents=[types.Part.from_bytes(data=data, mime_type="audio/wav"), PROMPT],
            config={
                "temperature": 0.0,
                "max_output_tokens": 8192,
                **({"thinking_config": {"thinking_budget": 0}} if "2.5" in model and "pro" not in model else {}),
            },
        )
        log.info("  done in %.1fs", time.monotonic() - started)
        parts.append(f"## From {label}\n\n{shift_timestamps((resp.text or '').strip(), int(offset))}\n")
    if not parts:
        parts.append("(no sound found in the recording)\n")
    out = run_dir / "transcript_audio.md"
    out.write_text(
        "# Transcript from the recorded audio (Gemini)\n\nTimestamps are from the start of audio.wav, "
        "the same clock as playback.html.\n\n" + "\n".join(parts),
        encoding="utf-8",
    )
    return out
