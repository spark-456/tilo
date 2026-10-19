"""Meeting events as JSON lines, so this bot can later run as one agent inside a larger system.

Input contract: meeting URL + agenda. Output contract: these events (events.jsonl and, if echo is on, stdout).
Types: meeting.joined, transcript.utterance, agenda.update, chat.posted, action_item.detected,
summary.ready, meeting.ended.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def remove_meet_links(value: Any) -> Any:
    """A meeting capability never enters local output, including pasted participant text."""
    if isinstance(value, str):
        return re.sub(r"(?:https?://)?meet\.google\.com/[^\s<>\"']+", "[Meet link removed]", value, flags=re.I)
    if isinstance(value, dict):
        return {k: remove_meet_links(v) for k, v in value.items() if k != "url"}
    if isinstance(value, (tuple, list)):
        return [remove_meet_links(v) for v in value]
    return value


class EventSink:
    def __init__(self, path: Path | None, meeting_id: str, echo: bool = False) -> None:
        self.path = path
        self.meeting_id = meeting_id
        self.echo = echo
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, type_: str, **data: Any) -> dict[str, Any]:
        event = {
            "v": 1,
            "type": type_,
            "ts": datetime.now(UTC).isoformat(timespec="seconds"),
            "meeting_id": self.meeting_id,
            **remove_meet_links(data),
        }
        line = json.dumps(event, ensure_ascii=False)
        if self.path:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        if self.echo:
            print("EVENT " + line, flush=True)
        return event
