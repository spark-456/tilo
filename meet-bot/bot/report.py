"""`report` and `audit`: read a run folder and say where the time went, then check the log against the audio.

Both are stdlib only and run on the host. `audit` measures end of the human turn -> first sound of the bot from the two
recordings (audio.wav = the meeting, bot.wav = what the bot sent into it), to within one 10 ms step, and compares it with
the first_sample mark in turns.jsonl.
"""

from __future__ import annotations

import json
import struct
import wave
from pathlib import Path
from typing import Any

from .trace import MARKS, load_turns, percentile

BUDGET_S = {"model": 1.30, "instant": 0.80}  # first sample after the end of the human turn (architecture section 4)
RMS_ON = 150.0  # same level the live voice-activity check uses
HOP_S = 0.01
MIN_SEGMENT_S = 0.08
MERGE_GAP_S = 0.35  # silence shorter than this stays inside one burst of sound
ANSWER_WINDOW_S = 30.0


# -- waveforms ---------------------------------------------------------------------------------------------------------
def _envelope(path: Path) -> tuple[list[float], float]:
    """RMS of each 10 ms step of a mono 16-bit WAV, and the step length in seconds."""
    with wave.open(str(path), "rb") as w:
        step = max(1, int(w.getframerate() * HOP_S))
        out: list[float] = []
        while chunk := w.readframes(step):
            n = len(chunk) // 2
            if n:
                v = struct.unpack("<" + "h" * n, chunk[: n * 2])
                out.append((sum(x * x for x in v) / n) ** 0.5)
        return out, step / w.getframerate()


def _segments(path: Path) -> list[tuple[float, float]]:
    env, step = _envelope(path)
    spans: list[list[float]] = []
    for i, level in enumerate(env):
        if level >= RMS_ON:
            t = i * step
            if spans and t - spans[-1][1] <= MERGE_GAP_S:
                spans[-1][1] = t + step
            else:
                spans.append([t, t + step])
    return [(a, b) for a, b in spans if b - a >= MIN_SEGMENT_S]


def _bot_offset(run: Path) -> float:
    """How much later the bot recording started than the meeting recording (seconds)."""
    try:
        clock = json.loads((run / "audio_clock.json").read_text(encoding="utf-8"))
        return float(clock["bot_start"]) - float(clock["audio_start"])
    except (OSError, ValueError, KeyError):
        return 0.0


def audit(run: Path) -> list[dict[str, Any]]:
    """End of each human turn -> first bot sound, measured on the recordings. Empty if the bot never made a sound."""
    if not (run / "bot.wav").is_file():
        return []
    bots = [(a + _bot_offset(run), b + _bot_offset(run)) for a, b in _segments(run / "bot.wav")]
    turns = [t for t in load_turns(run / "turns.jsonl") if t.get("speech_end_s") is not None]
    rows: list[dict[str, Any]] = []
    if turns:  # the log says where each human turn ended on the audio clock
        for i, turn in enumerate(turns):
            end = turn["speech_end_s"]
            limit = turns[i + 1]["speech_end_s"] if i + 1 < len(turns) else end + ANSWER_WINDOW_S
            start = next((a for a, _ in bots if end - 0.5 <= a < limit), None)
            if start is None:
                continue
            logged = turn.get("marks", {}).get("first_sample")
            row = {"turn": turn["turn"], "human_end_s": end, "bot_start_s": round(start, 3)}
            row["audio_s"] = round(start - end, 3)
            row["logged_s"] = logged
            row["delta_s"] = None if logged is None else round(start - end - logged, 3)
            rows.append(row)
        return rows
    if not (run / "audio.wav").is_file():
        return []
    humans = _segments(run / "audio.wav")
    used: set[int] = set()
    for start, _ in bots:  # each bot burst answers the latest human burst that began before it
        idx = max((i for i, (a, _) in enumerate(humans) if a <= start), default=None)
        if idx is None or idx in used:
            continue
        used.add(idx)
        end = humans[idx][1]
        rows.append(
            {
                "turn": len(rows) + 1,
                "human_end_s": round(end, 3),
                "bot_start_s": round(start, 3),
                "audio_s": round(start - end, 3),
            }
        )
    return rows


def render_audit(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "no bot sound found to audit (needs bot.wav from a run with voice replies)"
    lines = []
    for r in rows:
        extra = "" if r.get("logged_s") is None else f"  (log {r['logged_s']:.2f}s, difference {r['delta_s']:+.2f}s)"
        lines.append(
            f"turn {r['turn']}  human turn ended {r['human_end_s']:.2f}s  first bot sound {r['bot_start_s']:.2f}s  "
            f"gap {r['audio_s']:.2f}s{extra}"
        )
    return "\n".join(lines)


# -- the report --------------------------------------------------------------------------------------------------------
def _attempts(run: Path) -> list[dict[str, Any]]:
    path = run / "connections.jsonl"
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return [r for r in out if r.get("kind") == "attempt"]


def _stat(values: list[float]) -> str:
    p50, p90 = percentile(values, 50), percentile(values, 90)
    return "-" if p50 is None or p90 is None else f"p50 {p50:.2f} p90 {p90:.2f}"


def render_report(run: Path) -> str:
    turns = load_turns(run / "turns.jsonl")
    if not turns:
        return f"no turns recorded in {run} (turns.jsonl is missing or empty)"
    try:
        audited = {r["turn"]: r for r in audit(run)}
    except (OSError, wave.Error, EOFError):
        audited = {}
    lines: list[str] = []
    for t in turns:
        lines.append(
            f'turn {t["turn"]}  route={t["route"]}  outcome={t["outcome"]}  asked_by={t["asker"]}  "{t["text"]}"'
        )
        marks = t.get("marks", {})
        for name in MARKS:
            if name not in marks:
                continue
            note = ""
            if name == "first_sample":
                note = f"   (budget {BUDGET_S.get(t['route'], BUDGET_S['model']):.2f})"
                if t["turn"] in audited:
                    note += f"   audit {audited[t['turn']]['audio_s']:.2f}"
            lines.append(f"  {name:<15}{marks[name]:>6.2f}{note}")
    marks_of = [t.get("marks", {}) for t in turns]

    def span(a: str, b: str) -> list[float]:
        return [m[b] - m[a] for m in marks_of if a in m and b in m]

    retries = sum(1 for r in _attempts(run) if r.get("attempt", 1) > 1)
    lines.append(
        f"summary  n={len(turns)}  first_sample {_stat([m['first_sample'] for m in marks_of if 'first_sample' in m])}"
        f" | llm_ttft {_stat(span('llm_request', 'llm_first_token'))}"
        f" | tts_ttfb {_stat(span('tts_request', 'tts_first_pcm'))}"
        f" | barge stop {_stat(span('barge_start', 'barge_stop'))} | retries {retries}"
    )
    return "\n".join(lines)
