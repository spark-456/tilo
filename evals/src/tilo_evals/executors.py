"""Executors for the eval runner (EFF-07; PRD 6.6 "Record and replay").
`ReplayExecutor` reads a case's recording: JSONL TiloEvents plus an optional
final `{"outputs": {...}, "credits": n}` line (P8-06 spec). The live executor
needs `packages/providers` and is not built yet -- `--live` refuses without
`LIVE=1` and, even then, says so (EFF-01).

A recording that cannot be read or parsed raises `ExecutorError` rather than
letting a raw exception escape the runner: a bad recording must never crash
the whole pass (qa review, EFF-07). In particular, `credits` must be a
finite number that is at least 0 -- a negative or `NaN` value would otherwise
corrupt the credit-cap arithmetic in `runner.run_pass` (qa review repro:
`{"credits": -1000}` lowers `spent`; `{"credits": NaN}` makes every later
`spent + estimate > cap` check false).
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Protocol

from .checks import Outcome


class ExecutorError(Exception):
    """Raised when a case cannot be executed: no recording, a recording that
    cannot be found, or a recording that cannot be read or parsed (a
    malformed JSON line, a non-object line, or a non-numeric/negative/NaN
    credits value)."""


class Executor(Protocol):
    def run(self, case: Any) -> Outcome: ...


def _validated_credits(case: Any, raw: Any) -> float:
    if raw is None:
        return 0.0
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ExecutorError(f"case {case.id}: recording credits {raw!r} is not a number") from exc
    if not math.isfinite(value) or value < 0:
        raise ExecutorError(f"case {case.id}: recording credits must be a finite number >= 0, got {raw!r}")
    return value


def _validated_event(case: Any, event: dict[str, Any]) -> dict[str, Any]:
    """Checks every event field the runner reads (qa review round 2)."""
    trace = event.get("trace")
    if trace is not None and not isinstance(trace, dict):
        raise ExecutorError(f"case {case.id}: event trace must be an object, got {type(trace).__name__}")
    for key in ("model_role", "profile"):
        value = (trace or {}).get(key)
        if value is not None and not isinstance(value, str):
            raise ExecutorError(f"case {case.id}: event trace.{key} must be a string")
    return {**event, "credits": _validated_credits(case, event.get("credits"))}


class ReplayExecutor:
    """Replays a recorded case. A recording line with a "type" key is a
    TiloEvent; the one line without one (if present) is the final
    {"outputs": {...}, "credits": n} summary. Without a summary line the
    case's cost is the sum of its event credits."""

    def run(self, case: Any) -> Outcome:
        if not case.recording:
            raise ExecutorError(f"case {case.id}: no recording to replay")
        recording_path = Path(case.recording)
        if not recording_path.is_file():
            raise ExecutorError(f"case {case.id}: recording not found at {recording_path}")

        events: list[dict[str, Any]] = []
        outputs: dict[str, Any] = {}
        summary_credits: float | None = None

        try:
            text = recording_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise ExecutorError(f"case {case.id}: cannot read recording: {exc}") from exc
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except (ValueError, RecursionError) as exc:  # includes JSONDecodeError, int-digit limit
                raise ExecutorError(f"case {case.id}: malformed JSON line in recording: {exc}") from exc
            if not isinstance(record, dict):
                raise ExecutorError(
                    f"case {case.id}: recording line must be a JSON object, got {type(record).__name__}"
                )
            if "type" in record:
                events.append(_validated_event(case, record))
            else:
                outputs = record.get("outputs") or {}
                summary_credits = _validated_credits(case, record.get("credits"))

        # No summary line: the case costs what its events cost (qa review round 4).
        credits = summary_credits if summary_credits is not None else sum(e["credits"] for e in events)
        return Outcome(events=tuple(events), outputs=outputs, credits=credits)
