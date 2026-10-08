"""Replay a recorded transcript through the brain on a fake clock. Used by `run-mock` and the tests."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .brain import Agenda, Brain, ChatMessage
from .captions import TranscriptStore, Utterance
from .clock import FakeClock


@dataclass
class MockResult:
    brain: Brain
    messages: list[tuple[float, ChatMessage]]
    steps: int


def load_transcript(path: Path) -> list[Utterance]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            d = json.loads(line)
            out.append(Utterance(speaker=d["speaker"], text=d["text"], t=float(d["t"]), ts=d.get("ts", "")))
    return sorted(out, key=lambda u: u.t)


def run_mock(
    agenda: Agenda,
    transcript: list[Utterance],
    llm,
    duration_min: float,
    interval_s: float = 45,
    window_min: float = 5,
    out_dir: Path | None = None,
) -> MockResult:
    clock = FakeClock()
    brain = Brain(agenda, llm, duration_min)
    store = TranscriptStore(out_dir / "transcript.jsonl" if out_dir else None)
    pending = list(transcript)
    messages: list[tuple[float, ChatMessage]] = []
    steps = 0
    end = duration_min * 60
    while clock.now() < end:
        clock.advance(interval_s)
        now = min(clock.now(), end)
        while pending and pending[0].t <= now:
            store.append(pending.pop(0))
        result = brain.step(store.window(now, window_min), now)
        steps += 1
        if result.chat:
            brain.commit_chat(result.chat, now)
            messages.append((now, result.chat))
    if out_dir:
        brain.write_outputs(out_dir, end)
    return MockResult(brain, messages, steps)
