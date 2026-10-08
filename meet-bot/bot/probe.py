"""`stt-probe`: stream a recorded meeting's audio to ElevenLabs Scribe at real-time speed and report what it does.

Answers, with measurements instead of claims: does the key work on this plan, how long after the end of each phrase does
the final text arrive, are speakers labelled, and is the text right (compare with transcript_audio.md / playback.html).
"""

from __future__ import annotations

import asyncio
import time
import wave
from pathlib import Path

from .stt_stream import AudioGate, Final, ScribeStream


async def probe(wav_path: Path, speed: float = 1.0, keyterms: list[str] | None = None) -> int:
    with wave.open(str(wav_path), "rb") as w:
        pcm = w.readframes(w.getnframes())
    total_s = len(pcm) / 32000
    started = time.monotonic()
    skipped = 0.0  # silent stretches are skipped, not sent and not waited for
    rows: list[tuple[float, Final]] = []

    def virtual_now() -> float:  # position on the recording's own clock
        return (time.monotonic() - started) * speed + skipped

    def on_final(fin: Final) -> None:
        rows.append((virtual_now(), fin))

    stream = ScribeStream(lambda t: None, on_final, keyterms=keyterms or ["Tilo"])
    gate = AudioGate()
    q: asyncio.Queue = asyncio.Queue()
    task = asyncio.create_task(stream.run(q))
    frame = 3200
    try:
        for i in range(0, len(pcm), frame):
            t = i / 32000
            sent = gate.feed(pcm[i : i + frame], t)
            if not sent:
                skipped += 0.1  # nothing to send: jump ahead instead of waiting through silence
                continue
            for item in sent:
                q.put_nowait(item)
            await asyncio.sleep(0.1 / speed)
            if task.done():
                break
        q.put_nowait(None)
        await asyncio.wait_for(task, timeout=20)
    except Exception as e:
        print(f"probe stopped: {e}")
        return 1
    print(
        f"Sent {stream.total_sent_s:.0f} s of audio out of {total_s:.0f} s "
        f"({100 * stream.total_sent_s / total_s:.0f}%): silence is never sent.\n"
    )
    if not rows:
        print("No transcripts came back (no speech found, or the plan does not include realtime transcription).")
        return 1
    print(f"{len(rows)} committed phrase(s). 'lag' = seconds after the phrase ended that the text arrived.\n")
    for arrived, fin in rows:
        print(
            f"[{int(fin.start_s) // 60:02d}:{fin.start_s % 60:04.1f}] lag {arrived - fin.end_s:4.1f}s  "
            f"{fin.speaker_id or 'no-speaker-id'}: {fin.text}"
        )
    speakers = {f.speaker_id for _, f in rows if f.speaker_id}
    print(f"\nspeaker ids seen: {sorted(speakers) or 'none (diarization not returned)'}")
    return 0
