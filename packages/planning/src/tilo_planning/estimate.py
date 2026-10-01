"""Estimates (FR-INT-07, PRD 7.1): plan units x historical cost per unit type, as a credit range and a time
range. Plain arithmetic: no model, network or randomness. A unit type with no history refuses rather than
guesses. The default history is the seed table shipped with this package, which is empty at launch and filled
from the first eval pass (PRD 7.3)."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from importlib import resources
from typing import Any

SEED_FILE = "unit_cost_seed.json"


class UnknownUnitTypeError(LookupError):
    """A unit type has no cost history, so no estimate is given."""


@dataclass(frozen=True)
class UnitCost:
    """Historical cost of one unit of a type: low and high credits and seconds."""

    credits_min: float
    credits_max: float
    time_min_s: int
    time_max_s: int


def _checked(unit_type: str, cost: UnitCost) -> UnitCost:
    credits, times = (cost.credits_min, cost.credits_max), (cost.time_min_s, cost.time_max_s)
    if not all(isinstance(c, int | float) and math.isfinite(c) and c >= 0 for c in credits):
        raise ValueError(f"FR-INT-07: {unit_type!r} credits must be finite and non-negative")
    if not all(isinstance(t, int) and not isinstance(t, bool) and t >= 0 for t in times):
        raise ValueError(f"FR-INT-07: {unit_type!r} times must be non-negative whole seconds")
    return cost


def load_seed_history() -> dict[str, UnitCost]:
    """The package's seed table (`seed: true`), with each type's ranges checked for order."""
    table = json.loads(resources.files("tilo_planning").joinpath(SEED_FILE).read_text(encoding="utf-8"))
    if table.get("seed") is not True:
        raise ValueError(f"FR-INT-07: {SEED_FILE} must be marked as a seed")
    history = {name: _checked(name, UnitCost(**row)) for name, row in table["unit_types"].items()}
    for name, cost in history.items():
        if cost.credits_min > cost.credits_max or cost.time_min_s > cost.time_max_s:
            raise ValueError(f"FR-INT-07: {name!r} has a range whose minimum is above its maximum")
    return history


def estimate_units(units: list[dict[str, Any]], *, history: dict[str, UnitCost] | None = None) -> dict[str, Any]:
    """`{"credits": credit_range, "time": time_range}` summed over `units` (plan.schema.json units)."""
    table = load_seed_history() if history is None else history
    missing = sorted({u["unit_type"] for u in units} - table.keys())
    if missing:
        raise UnknownUnitTypeError(f"FR-INT-07: no cost history for unit types {missing}")
    costs = [_checked(u["unit_type"], table[u["unit_type"]]) for u in units]
    return {
        "credits": {"min": sum(c.credits_min for c in costs), "max": sum(c.credits_max for c in costs)},
        "time": {"min_s": sum(c.time_min_s for c in costs), "max_s": sum(c.time_max_s for c in costs)},
    }
