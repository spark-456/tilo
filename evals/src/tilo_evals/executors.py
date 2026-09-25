"""Executors for the eval runner (EFF-07; PRD 6.6 "Record and replay").
`ReplayExecutor` reads a case's recording: JSONL TiloEvents plus an optional
final `{"outputs": {...}, "credits": n}` line (P8-06 spec). `FakeExecutor` is
a canned stand-in for unit tests. The live executor needs
`packages/providers` and is not built yet -- `--live` refuses without
`LIVE=1` and, even then, says so (EFF-01).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .checks import Outcome


class ExecutorError(Exception):
    """Raised when a case cannot be executed: no recording, or a recording
    that cannot be read."""


class Executor(Protocol):
    def run(self, case: Any) -> Outcome: ...


class ReplayExecutor:
    """Replays a recorded case. A recording line with a "type" key is a
    TiloEvent; the one line without one (if present) is the final
    {"outputs": {...}, "credits": n} summary."""

    def run(self, case: Any) -> Outcome:
        if not case.recording:
            raise ExecutorError(f"case {case.id}: no recording to replay")
        recording_path = Path(case.recording)
        if not recording_path.is_file():
            raise ExecutorError(f"case {case.id}: recording not found at {recording_path}")

        events: list[dict[str, Any]] = []
        outputs: dict[str, Any] = {}
        credits = 0.0

        text = recording_path.read_text(encoding="utf-8")
        for line in text.splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            if "type" in record:
                events.append(record)
            else:
                outputs = record.get("outputs") or {}
                credits = float(record.get("credits") or 0.0)

        return Outcome(events=tuple(events), outputs=outputs, credits=credits)


@dataclass
class FakeExecutor:
    """Returns a canned Outcome regardless of the case; used for tests."""

    outcome: Outcome = field(default_factory=Outcome)

    def run(self, case: Any) -> Outcome:
        return self.outcome


class LiveNotBuiltError(Exception):
    """--live is refused even with LIVE=1: the live executor needs
    packages/providers, which this ticket does not build."""
