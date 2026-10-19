"""Latency log: how long each stage takes between someone speaking and the reply appearing in chat.

Written to out/<run>/latency.jsonl (one JSON object per line) so it can be read or charted afterwards.
Stages for a question: caption first visible -> question detected (waits for the sentence to finish) -> model call ->
typing into chat. Speech-to-caption lag happens inside Meet and cannot be measured from here (typically 1-3 s).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .events import remove_meet_links


class Timeline:
    def __init__(self, path: Path | None) -> None:
        self.path = path
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, kind: str, **data: Any) -> None:
        if not self.path:
            return
        row = {"ts": datetime.now(UTC).isoformat(timespec="milliseconds"), "kind": kind, **data}
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(remove_meet_links(row), ensure_ascii=False) + "\n")
