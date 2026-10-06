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
    """A recorded cost: absent is 0; otherwise a finite int or float >= 0 (never a bool or a string)."""
    if raw is None:
        return 0.0
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        raise ExecutorError(f"case {case.id}: recording credits must be a number, got {type(raw).__name__}")
    try:
        value = float(raw)
    except OverflowError as exc:  # an int too large for a float, such as 10**400
        raise ExecutorError(f"case {case.id}: recording credits are too large") from exc
    if not math.isfinite(value) or value < 0:
        raise ExecutorError(f"case {case.id}: recording credits must be a finite number >= 0")
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
    present) is the final `{"outputs": {...}, "credits": n}` summary. The case costs the larger of the
    summary's credits and the sum of its event credits. `base` is the directory a case's relative `recording`
    path is read from."""

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
        return outcome_of(case, events, outputs, summary_credits)


def outcome_of(
    case: Any, events: list[dict[str, Any]], outputs: dict[str, Any], summary_credits: float | None
) -> Outcome:
    events_total = sum(e["credits"] for e in events)
    # The cap charges the larger of the summary and the event sum, so a recording cannot under-charge it.
    credits = max(events_total, summary_credits or 0.0)
    if not math.isfinite(credits):
        raise ExecutorError(f"case {case.id}: recording credits are too large")
    return Outcome(events=tuple(events), outputs=outputs, credits=credits)


def parse_batch_answer(case: Any, text: str | None) -> Outcome:
    """EFF-05: a batch answer is `{"events": [...], "outputs": {...}, "credits": n}`, validated like a recording."""
    try:
        answer = json.loads(text or "")
    except (ValueError, RecursionError) as exc:
        raise ExecutorError(f"case {case.id}: batch answer is not valid JSON: {exc}") from exc
    events = answer.get("events", []) if isinstance(answer, dict) else None
    outputs = answer.get("outputs", {}) if isinstance(answer, dict) else None
    if not isinstance(events, list) or not all(isinstance(e, dict) for e in events) or not isinstance(outputs, dict):
        raise ExecutorError(f"case {case.id}: batch answer needs an events list and an outputs object")
    return outcome_of(case, [_event(case, e) for e in events], outputs, _credits(case, answer.get("credits")))


class BatchExecutor:
    """EFF-05: serves each case's outcome from the results of one batch job (`BatchResult`s by case id). A failed
    item or a bad answer makes that case not runnable, never the pass crash."""

    def __init__(self, results: Any) -> None:
        self._results = {r.custom_id: r for r in results}

    def run(self, case: Any) -> Outcome:
        result = self._results.get(case.id)
        if result is None or result.status != "ok" or result.response is None:
            reason = result.error if result is not None else "no result returned"
            raise ExecutorError(f"case {case.id}: batch item failed: {reason}")
        return parse_batch_answer(case, result.response.text)
