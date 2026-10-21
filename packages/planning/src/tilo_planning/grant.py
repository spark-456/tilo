"""RUN-SPEED (live, 21 Oct 2026): the credits a plan needs, so the grant the confirm card shows covers its own calls.

A nine-unit run failed on a 60-credit grant: the Director's estimate under-priced it and a late unit could not afford
one call. `plan_need` prices a plan as every unit's least call at its role's output cap (`floor(role)`, the provider
layer's `call_floor`) plus NEED_MARGIN: with that grant, every unit can still afford a call even if each before it spent
its whole floor. Before approval only the approach is known, so `sketch_need` prices a stand-in plan: the units code
always adds for the brief's deliverables (the compiler's own `_with_deliver` and `with_design_team`) and the Director's
own working units, one more than the approach runs at once, each at the dearest worker role. Structured fields only,
never the task's words (GEN-06)."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from tilo_planning.compiler import _with_deliver
from tilo_planning.deliverable_teams import with_design_team

NEED_MARGIN = 0.25  # input, repairs and a second call in a unit, over the least call
NOMINAL_INPUT_CHARS = 12_000  # the input each least call is priced with (a unit's brief, skill and upstream items)
WORKER_ROLES = ("specialist", "writer", "verifier")

Floor = Callable[[str], float]


def plan_need(units: Sequence[Mapping[str, Any]], floor: Floor) -> float:
    """Every unit's least call at its role's output cap, plus the margin."""
    return (1 + NEED_MARGIN) * math.fsum(floor(str(unit["role"])) for unit in units)


def sketch_need(brief: Mapping[str, Any], approach: Mapping[str, Any], floor: Floor) -> float:
    """`plan_need` of the plan the approach is likely to compile to, before the Director has planned it."""
    parallel = (approach.get("dimensions") or {}).get("parallelism")
    own = (parallel if isinstance(parallel, int) and 1 <= parallel <= 6 else 1) + 1
    placeholders = [
        {"id": f"U{n}", "unit_type": "work", "title": "Work", "role": "specialist", "district": "D1", "skills": [],
         "connectors": [], "actions": [], "depends_on": []}
        for n in range(1, own + 1)
    ]  # fmt: skip
    added = with_design_team(_with_deliver(placeholders, dict(brief)), dict(brief))[own:]
    dearest = max(floor(role) for role in WORKER_ROLES)
    return (1 + NEED_MARGIN) * own * dearest + plan_need(added, floor)
