"""Flag store (NFR-24 replay_only, P8-04 claims_frozen); unset flags read False. A Firestore store comes later."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

Change = tuple[bool, str, datetime]  # (value, reason, at)


class FlagStore(Protocol):
    def get(self, name: str) -> bool: ...
    def set(self, name: str, value: bool, *, reason: str) -> None: ...
    def history(self, name: str) -> tuple[Change, ...]: ...


@dataclass
class InMemoryFlagStore:
    _history: dict[str, list[Change]] = field(default_factory=dict)

    def get(self, name: str) -> bool:
        changes = self._history.get(name)
        return changes[-1][0] if changes else False

    def set(self, name: str, value: bool, *, reason: str) -> None:
        if not isinstance(value, bool):
            raise TypeError(f"flag {name!r} takes a bool, got {type(value).__name__}")
        self._history.setdefault(name, []).append((value, reason, datetime.now(UTC)))

    def history(self, name: str) -> tuple[Change, ...]:
        return tuple(self._history.get(name, ()))
