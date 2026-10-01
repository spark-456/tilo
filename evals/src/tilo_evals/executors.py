"""Executors for the eval runner (EFF-07; PRD 6.6 "Record and replay", EFF-01).

`ReplayExecutor` reads a case's recording: JSONL TiloEvents plus an optional final
`{"outputs": {...}, "credits": n}` line. It makes no call of any kind. A live executor would go through
`packages/providers` and is not built: `--live` refuses without `LIVE=1` and, with it, says so.

A recording that cannot be read or parsed raises `ExecutorError`, never a raw exception: a bad recording
must not crash the pass. `credits` must be a finite number >= 0, since a negative or NaN value would
corrupt the credit-cap arithmetic in `runner.run_pass`.
"""

import json
import math
from pathlib import Path
from typing import Any, Protocol

from .checks import Outcome


class ExecutorError(Exception):
    """A case cannot be executed: no recording, an unreadable or malformed one, or a bad credits value."""


class Executor(Protocol):
    def run(self, case: Any) -> Outcome: ...


def _credits(case: Any, raw: Any) -> float:
    if raw is None:
        return 0.0
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ExecutorError(f"case {case.id}: recording credits {raw!r} is not a number") from exc
    if not math.isfinite(value) or value < 0:
        raise ExecutorError(f"case {case.id}: recording credits must be a finite number >= 0, got {raw!r}")
    return value


def _event(case: Any, event: dict[str, Any]) -> dict[str, Any]:
    """Validates every event field the runner reads (trace, model_role, profile, credits)."""
    trace = event.get("trace")
    if trace is not None and not isinstance(trace, dict):
        raise ExecutorError(f"case {case.id}: event trace must be an object, got {type(trace).__name__}")
    for key in ("model_role", "profile"):
        value = (trace or {}).get(key)
        if value is not None and not isinstance(value, str):
            raise ExecutorError(f"case {case.id}: event trace.{key} must be a string")
    return {**event, "credits": _credits(case, event.get("credits"))}


class ReplayExecutor:
    """Replays a recorded case. A line with a "type" key is a TiloEvent; the one line without one (if
    present) is the final `{"outputs": {...}, "credits": n}` summary. Without a summary the case costs the
    sum of its event credits. `base` is the directory a case's relative `recording` path is read from."""

    def __init__(self, base: Path = Path(".")) -> None:
        self._base = base

    def run(self, case: Any) -> Outcome:
        if not case.recording:
            raise ExecutorError(f"case {case.id}: no recording to replay")
        path = self._base / case.recording
        if not path.is_file():
            raise ExecutorError(f"case {case.id}: recording not found at {path}")
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise ExecutorError(f"case {case.id}: cannot read recording: {exc}") from exc

        events: list[dict[str, Any]] = []
        outputs: dict[str, Any] = {}
        summary_credits: float | None = None
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except (ValueError, RecursionError) as exc:  # JSONDecodeError, int-digit limit, deep nesting
                raise ExecutorError(f"case {case.id}: malformed JSON line in recording: {exc}") from exc
            if not isinstance(record, dict):
                raise ExecutorError(f"case {case.id}: recording line must be a JSON object")
            if "type" in record:
                events.append(_event(case, record))
            else:
                outputs = record.get("outputs", {})
                if not isinstance(outputs, dict):
                    raise ExecutorError(f"case {case.id}: recording outputs must be an object")
                summary_credits = _credits(case, record.get("credits"))
        credits = summary_credits if summary_credits is not None else sum(e["credits"] for e in events)
        return Outcome(events=tuple(events), outputs=outputs, credits=credits)
