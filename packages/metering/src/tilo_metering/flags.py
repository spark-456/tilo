"""Flag store (NFR-24 kill switch, P8-04 `claims_frozen`). Flag names used
elsewhere in the metering package: "replay_only", "claims_frozen". A
Firestore-emulator-backed store comes later; this ticket only needs the
protocol and an in-memory implementation for tests and local runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol


@dataclass(frozen=True)
class FlagChange:
    """One recorded change to a flag's value."""

    value: bool
    reason: str
    at: datetime


class FlagStore(Protocol):
    def get(self, name: str) -> bool: ...
    def set(self, name: str, value: bool, *, reason: str) -> None: ...
    def history(self, name: str) -> tuple[FlagChange, ...]: ...


@dataclass
class InMemoryFlagStore:
    """A `FlagStore` backed by a plain dict, defaulting every unset flag to
    False. Every `set` is appended to that flag's history, never overwritten."""

    _values: dict[str, bool] = field(default_factory=dict)
    _history: dict[str, list[FlagChange]] = field(default_factory=dict)

    def get(self, name: str) -> bool:
        return self._values.get(name, False)

    def set(self, name: str, value: bool, *, reason: str) -> None:
        self._values[name] = value
        self._history.setdefault(name, []).append(FlagChange(value=value, reason=reason, at=datetime.now(UTC)))

    def history(self, name: str) -> tuple[FlagChange, ...]:
        return tuple(self._history.get(name, ()))
