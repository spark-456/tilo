"""tilo_providers.meeting: the per-meeting cap on the bot's provider calls (FR-MTG-11), read from `config/meeting.yaml`.

The meeting bot answers questions that anyone in the call can ask, and its model, speech and voice calls run outside
the router's budget (SEC-16 spend caps are not wired for the bot, BQ-MTG11-9). This bounds one meeting by count instead:
`CallCounter.take(kind)` is True while the cap for `model` or `speech` is not reached, and False after, so the caller
degrades (transcript only, the local voice) and says so once (`newly_capped`). A refused call is not counted. The counts
live in the process: one bot process is one meeting."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from tilo_providers.config import ProviderConfigError

KINDS = ("model", "speech")


@dataclass(frozen=True)
class MeetingCaps:
    max_model_calls: int  # analysis and direct-answer model calls, one per router call (primary plus fallback: one)
    max_speech_calls: int  # speech-to-text segments and voice replies


def _cap(section: dict[str, Any], name: str) -> int:
    value = section.get(name)
    if type(value) is not int or value <= 0:
        raise ProviderConfigError(f"FR-MTG-11: config/meeting.yaml `{name}` must be a positive whole number")
    return value


def load_meeting_caps(path: Path | str) -> MeetingCaps:
    """Loads and validates `config/meeting.yaml`; a missing file, section or bad number fails start-up."""
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ProviderConfigError(f"could not read {path}: {type(error).__name__}") from None
    section = raw.get("meeting") if isinstance(raw, dict) else None
    if not isinstance(section, dict):
        raise ProviderConfigError(f"{path} must have a `meeting` mapping")
    return MeetingCaps(_cap(section, "max_model_calls"), _cap(section, "max_speech_calls"))


@dataclass
class CallCounter:
    caps: MeetingCaps
    used: dict[str, int] = field(default_factory=lambda: dict.fromkeys(KINDS, 0))
    _announced: set[str] = field(default_factory=set)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def _limit(self, kind: str) -> int:
        if kind not in KINDS:
            raise ValueError(f"unknown call kind {kind!r}; expected one of {KINDS}")
        return self.caps.max_model_calls if kind == "model" else self.caps.max_speech_calls

    def take(self, kind: str) -> bool:
        limit = self._limit(kind)
        with self._lock:
            if self.used[kind] >= limit:
                return False
            self.used[kind] += 1
            return True

    def newly_capped(self, kind: str) -> bool:
        """True once per kind, the first time it is asked after the cap is reached (so the log line appears once)."""
        limit = self._limit(kind)
        with self._lock:
            if self.used[kind] < limit or kind in self._announced:
                return False
            self._announced.add(kind)
            return True
