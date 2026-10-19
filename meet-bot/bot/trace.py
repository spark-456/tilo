"""The turn trace: one row per human turn in out/<run>/turns.jsonl, with every stage timed against the end of the human turn.

Marks are seconds relative to `speech_end` (negative = before it). `speech_end_s` is the same moment on the audio clock
(seconds into audio.wav), which lets `audit` check the log against the recorded waveforms.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol

from .events import remove_meet_links

MARKS = (
    "addressed",
    "probable_end",
    "confirmed_end",
    "stt_final",
    "llm_request",
    "llm_first_token",
    "first_sentence",
    "tts_request",
    "tts_first_pcm",
    "first_sample",
    "barge_start",
    "barge_duck",
    "barge_stop",
    "playback_end",
    "chat_posted",
)


class Clock(Protocol):
    def now(self) -> float: ...


def percentile(values: Sequence[float], pct: float) -> float | None:
    """Linear interpolation between the closest ranks (the usual 'inclusive' method); None for no data."""
    data = sorted(values)
    if not data:
        return None
    rank = (len(data) - 1) * pct / 100
    lo = int(rank)
    hi = min(lo + 1, len(data) - 1)
    return data[lo] + (data[hi] - data[lo]) * (rank - lo)


class Turn:
    def __init__(
        self, clock: Clock, turn_id: int, asker: str, text: str, speech_end: float, source: str, route: str
    ) -> None:
        self.clock, self.id, self.asker, self.text = clock, turn_id, asker, text
        self.speech_end, self.speech_end_source, self.route = speech_end, source, route
        self.marks: dict[str, float] = {}  # clock values; written relative to speech_end

    def mark(self, name: str, at: float | None = None) -> None:
        if name not in MARKS:
            raise ValueError(f"unknown turn mark {name!r}")
        self.marks[name] = self.clock.now() if at is None else at


class TurnTrace:
    def __init__(self, path: Path | None, clock: Clock, audio_start: float = 0.0) -> None:
        self.path, self.clock, self.audio_start = path, clock, audio_start
        self._n = 0
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)

    def new_turn(
        self, asker: str, text: str, speech_end: float, speech_end_source: str = "estimate", route: str = "model"
    ) -> Turn:
        self._n += 1
        return Turn(self.clock, self._n, asker, text, speech_end, speech_end_source, route)

    def finish(self, turn: Turn, outcome: str) -> None:
        """outcome: spoken | interrupted | chat_only | failed | cancelled | no_reply"""
        if not self.path:
            return
        row: dict[str, Any] = {
            "v": 1,
            "turn": turn.id,
            "route": turn.route,
            "outcome": outcome,
            "asker": turn.asker,
            "text": turn.text[:200],
            "speech_end_s": round(turn.speech_end - self.audio_start, 3),
            "speech_end_source": turn.speech_end_source,
            "marks": {k: round(v - turn.speech_end, 3) for k, v in turn.marks.items()},
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(remove_meet_links(row), ensure_ascii=False) + "\n")


def load_turns(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:  # a half-written last line after a crash
            continue
    return rows
