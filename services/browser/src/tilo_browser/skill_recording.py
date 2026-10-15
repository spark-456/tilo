"""Owner-scoped browser recording with secure-field checks and masking before storage."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from tilo_browser.egress import sanitise_url
from tilo_browser.masking import mask_text
from tilo_browser.worker import BrowserWorker

EventKind = Literal["navigate", "click", "type", "scroll", "download", "submit", "sign_in_pause"]
MAX_EVENTS = 200
_ID = re.compile(r"[A-Za-z0-9_-]{1,80}\Z")
_INPUT_CAPABILITY = object()


@dataclass(frozen=True)
class RecordedEvent:
    sequence: int
    kind: EventKind
    url: str
    target: str
    selector: str | None = None
    value: str | None = None
    observation: str = ""
    destination: str | None = None
    _input_capability: object | None = field(default=None, init=False, repr=False, compare=False)

    @classmethod
    def create(
        cls,
        *,
        sequence: int,
        kind: EventKind,
        url: str,
        target: str = "",
        selector: str | None = None,
        value: str | None = None,
        observation: str = "",
        destination: str | None = None,
        _capability: object | None = None,
    ) -> RecordedEvent:
        if type(sequence) is not int or not 1 <= sequence <= MAX_EVENTS:
            raise ValueError("recording sequence out of range")
        if kind not in {"navigate", "click", "type", "scroll", "download", "submit", "sign_in_pause"}:
            raise ValueError("unsupported recording event")
        if kind == "type" and value is not None and _capability is not _INPUT_CAPABILITY:
            raise ValueError("typed values require a browser-worker field check")
        event = cls(
            sequence,
            kind,
            sanitise_url(url),
            "sign-in required" if kind == "sign_in_pause" else _safe_line(target, 200) or "",
            None if kind == "sign_in_pause" else _safe_line(selector, 200),
            mask_text(value) if kind == "type" and value is not None else None,
            "" if kind == "sign_in_pause" else mask_text(observation),
            _safe_line(destination, 512),
        )
        if _capability is _INPUT_CAPABILITY:
            object.__setattr__(event, "_input_capability", _INPUT_CAPABILITY)
        return event


def _safe_line(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    if type(value) is not str:
        raise ValueError("recording text must be a string")
    result = mask_text(value.strip())
    if len(result) > limit or "\n" in result or "\r" in result:
        raise ValueError("recording text is invalid")
    return result


class JsonlRecordingStore:
    """Append-only files partitioned by owner. Inputs are canonicalized again on every append."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _path(self, owner: str, recording_id: str) -> Path:
        if not _ID.fullmatch(owner) or not _ID.fullmatch(recording_id):
            raise ValueError("invalid recording identity")
        root = self.root.resolve()
        path = (root / owner / f"{recording_id}.jsonl").resolve()
        if not path.is_relative_to(root):
            raise ValueError("recording path is outside storage root")
        return path

    def append(self, owner: str, recording_id: str, event: RecordedEvent) -> None:
        if event.kind == "type" and event.value is not None and event._input_capability is not _INPUT_CAPABILITY:
            raise ValueError("unverified typed value refused")
        path = self._path(owner, recording_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = self.read(owner, recording_id)
        if len(rows) >= MAX_EVENTS or event.sequence != len(rows) + 1:
            raise ValueError("recording sequence or size limit")
        safe = RecordedEvent.create(
            sequence=event.sequence,
            kind=event.kind,
            url=event.url,
            target=event.target,
            selector=event.selector,
            value=event.value,
            observation=event.observation,
            destination=event.destination,
            _capability=event._input_capability,
        )
        row = {
            name: getattr(safe, name)
            for name in ("sequence", "kind", "url", "target", "selector", "value", "observation", "destination")
        }
        row["input_verified"] = safe._input_capability is _INPUT_CAPABILITY
        payload = (json.dumps(row, ensure_ascii=True, separators=(",", ":")) + "\n").encode()
        fd = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
        try:
            offset = 0
            while offset < len(payload):
                offset += os.write(fd, payload[offset:])
            os.fsync(fd)
        finally:
            os.close(fd)

    def read(self, owner: str, recording_id: str) -> list[RecordedEvent]:
        path = self._path(owner, recording_id)
        if not path.exists():
            return []
        events: list[RecordedEvent] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            verified = row.pop("input_verified", False)
            capability = _INPUT_CAPABILITY if verified else None
            event = RecordedEvent.create(**row, _capability=capability)
            if event.sequence != len(events) + 1:
                raise ValueError("recording sequence is invalid")
            events.append(event)
            if len(events) > MAX_EVENTS:
                raise ValueError("recording size limit")
        return events

    def delete(self, owner: str, recording_id: str) -> None:
        self._path(owner, recording_id).unlink(missing_ok=True)


class RecordingSession:
    """Create events; typing is stored only after BrowserWorker confirms a non-secure input."""

    def __init__(self, store: JsonlRecordingStore, worker: BrowserWorker, *, owner: str, recording_id: str) -> None:
        self.store, self.worker, self.owner, self.recording_id = store, worker, owner, recording_id
        self.sequence = len(store.read(owner, recording_id))

    def record(
        self,
        *,
        kind: EventKind,
        url: str,
        target: str = "",
        selector: str | None = None,
        value: str | None = None,
        observation: str = "",
        destination: str | None = None,
    ) -> RecordedEvent:
        capability = None
        if kind == "type" and value is not None:
            ref = selector[1:] if selector and selector.startswith("#") else ""
            status = self.worker.classify_recorded_input(ref)
            if status == "secure":
                value, selector, target = None, None, "secure field"
            elif status != "nonsecure":
                raise ValueError("typed field is not a verified editable input")
            else:
                capability = _INPUT_CAPABILITY
        event = RecordedEvent.create(
            sequence=self.sequence + 1,
            kind=kind,
            url=url,
            target=target,
            selector=selector,
            value=value,
            observation=observation,
            destination=destination,
            _capability=capability,
        )
        self.store.append(self.owner, self.recording_id, event)
        self.sequence = event.sequence
        return event
