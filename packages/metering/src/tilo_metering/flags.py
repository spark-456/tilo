"""Flag store (NFR-24 kill switch, P8-04 claims_frozen). In-memory only; a Firestore store comes later."""

from __future__ import annotations

from collections import namedtuple
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

FlagChange = namedtuple("FlagChange", "value reason at")


class FlagStore(Protocol):
    def get(self, name: str) -> bool: ...
    def set(self, name: str, value: bool, *, reason: str) -> None: ...
    def history(self, name: str) -> tuple[FlagChange, ...]: ...


@dataclass
class InMemoryFlagStore:
    """Backed by a plain dict; every unset flag defaults to False."""

    _values: dict[str, bool] = field(default_factory=dict)
    _history: dict[str, list[FlagChange]] = field(default_factory=dict)

    def get(self, name: str) -> bool:
        return self._values.get(name, False)

    def set(self, name: str, value: bool, *, reason: str) -> None:
        self._values[name] = value
        self._history.setdefault(name, []).append(FlagChange(value, reason, datetime.now(UTC)))

    def history(self, name: str) -> tuple[FlagChange, ...]:
        return tuple(self._history.get(name, ()))
