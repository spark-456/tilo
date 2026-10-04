"""Credits-saved method (FR-MTR-06, PRD 14.3, event rule EV-09, meter rule MT-05).

A reuse saves what the result cost the first time (`origin_cost`) minus the lookup (`lookup_cost`), nothing else.
The figure is computed here from those two costs; `data.saved` is only cross-checked, never trusted, and a hit that
disagrees raises instead of being summed. Pure functions: no I/O, no model, no clock.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from typing import Any

HIT_TYPE = "memory.hit"
_TOLERANCE = 1e-9


class InconsistentMemoryHit(ValueError):
    """A `memory.hit` whose `saved` is not `origin_cost - lookup_cost` (EV-09)."""


def _event_id(event: Mapping[str, Any]) -> str:
    event_id = event.get("id")
    if not isinstance(event_id, str) or not event_id:
        raise ValueError("memory.hit event has no id")
    return event_id


def _cost(event: Mapping[str, Any], data: Mapping[str, Any], field: str) -> float:
    value = data.get(field)
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value) or value < 0:
        raise ValueError(f"memory.hit {_event_id(event)}: {field} must be a finite non-negative number")
    return float(value)


def hit_saving(event: Mapping[str, Any]) -> float:
    """`origin_cost - lookup_cost` of one `memory.hit`; ValueError if the hit is malformed or saved nothing sane."""
    event_id = _event_id(event)
    data = event.get("data")
    if not isinstance(data, Mapping):
        raise ValueError(f"memory.hit {event_id}: data is not an object")
    origin = _cost(event, data, "origin_cost")
    lookup = _cost(event, data, "lookup_cost")
    saved = _cost(event, data, "saved")
    saving = origin - lookup
    if saving < 0:
        raise InconsistentMemoryHit(f"memory.hit {event_id}: lookup_cost exceeds origin_cost")
    if not math.isclose(saved, saving, rel_tol=1e-9, abs_tol=_TOLERANCE):
        raise InconsistentMemoryHit(f"memory.hit {event_id}: saved is not origin_cost - lookup_cost")
    return saving


def credits_saved(events: Iterable[Mapping[str, Any]], *, run_id: str | None = None) -> float:
    """Sum of `hit_saving` over `memory.hit` events, each event id once, optionally for one run."""
    seen: set[str] = set()
    savings: list[float] = []
    for event in events:
        if event.get("type") != HIT_TYPE:
            continue
        event_id = _event_id(event)
        if event_id in seen:
            continue
        saving = hit_saving(event)  # every hit is checked, whatever run it belongs to
        seen.add(event_id)
        if run_id is None or event.get("run_id") == run_id:
            savings.append(saving)
    return math.fsum(savings)
