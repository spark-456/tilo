"""Memory checked before asking (FR-INT-05, PRD 13.1). Preferences and past answers (decisions) that fill a
brief field are applied in planning instead of asking again, each with its citation. `MemoryLookup` is the
seam for P7's real stores (Memory Bank preferences, Firestore decisions); `InMemoryPreferenceStore` is the
local fake."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class MemoryHit:
    field: str
    value: str
    kind: Literal["preference", "decision"]
    ref: str
    recorded_at: str
    origin_cost: float  # credits the answer cost when it was first obtained
    lookup_cost: float  # credits this lookup cost

    @property
    def citation(self) -> dict[str, str]:
        return {"kind": self.kind, "ref": self.ref, "recorded_at": self.recorded_at}

    @property
    def saved(self) -> float:
        return self.origin_cost - self.lookup_cost


class MemoryLookup(ABC):
    @abstractmethod
    def lookup(self, brief: dict[str, Any], candidate_fields: Iterable[str]) -> list[MemoryHit]:
        """Known answers for any of `candidate_fields` (the brief fields that would otherwise be asked)."""


class InMemoryPreferenceStore(MemoryLookup):
    """One stored answer per brief field, for local runs and tests."""

    def __init__(self) -> None:
        self._entries: dict[str, MemoryHit] = {}

    def set_preference(
        self,
        field: str,
        value: str,
        *,
        ref: str,
        recorded_at: str,
        origin_cost: float,
        lookup_cost: float,
        kind: Literal["preference", "decision"] = "preference",
    ) -> None:
        if lookup_cost < 0 or origin_cost < lookup_cost:
            raise ValueError("a stored answer must cost at least as much to obtain as to look up")
        self._entries[field] = MemoryHit(field, value, kind, ref, recorded_at, origin_cost, lookup_cost)

    def lookup(self, brief: dict[str, Any], candidate_fields: Iterable[str]) -> list[MemoryHit]:
        return [self._entries[f] for f in sorted(set(candidate_fields)) if f in self._entries]
