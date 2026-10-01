"""FR-INT-07 (PRD 7.1): "Estimates come from plan units x historical cost per unit type, shown
as a range." Acceptance test: "EV-03 median within +/-25% on the eval set" -- EV-03's accuracy
bar belongs to the eval harness (`evals/`), not this ticket; this ticket tests the arithmetic and
range shape only, as instructed.

PRD 7.3 open item: "Unit-type cost history is empty at launch; seed it from the first eval pass."
So the seed table is data the builder supplies later (from config or the first eval pass); these
tests pass an explicit history mapping, never the (still-empty) default.

Design (this ticket -- `tilo_planning.estimate` does not exist yet, from the PRD 7.1 FR-INT-07 row
plus `plan.schema.json#/$defs/unit.unit_type` and `common.schema.json#/$defs/credit_range` /
`#/$defs/time_range`): `estimate_units(units, history)` sums each unit's historical per-unit-type
low and high cost -- plain arithmetic, never a model call (the ticket brief: "the model never
supplies the numbers") -- and returns a `{"credits": credit_range, "time": time_range}` mapping in
exactly those two contract shapes. An unused unit_type refuses rather than guesses, matching
`tilo_metering.PriceBook`'s own "refuse, never guess" rule for the same reason (PL-06 style).

Public interface: `tilo_planning.estimate.estimate_units`, `.UnitCost`, `.UnknownUnitTypeError`.
"""

from __future__ import annotations

import ast
import pathlib

from _planning_contracts_lib import assert_valid_credit_range, assert_valid_time_range
from tilo_planning.estimate import UnitCost, UnknownUnitTypeError, estimate_units


def _unit(unit_id: str, unit_type: str) -> dict:
    return {
        "id": unit_id,
        "unit_type": unit_type,
        "title": f"Unit {unit_id}",
        "role": "specialist",
        "district": "D1",
        "skills": [],
        "connectors": [],
        "actions": [],
        "depends_on": [],
    }


_HISTORY = {
    "quote_extracted": UnitCost(credits_min=10, credits_max=15, time_min_s=60, time_max_s=90),
    "summary_written": UnitCost(credits_min=20, credits_max=30, time_min_s=120, time_max_s=180),
}


def test_FR_INT_07_estimate_is_plan_units_times_historical_cost_arithmetic():
    units = [
        _unit("U1", "quote_extracted"),
        _unit("U2", "quote_extracted"),
        _unit("U3", "summary_written"),
    ]

    estimate = estimate_units(units, history=_HISTORY)

    # Deterministic arithmetic, not an approximation: 2 x quote_extracted + 1 x summary_written.
    assert estimate["credits"] == {"min": 2 * 10 + 20, "max": 2 * 15 + 30}
    assert estimate["time"] == {"min_s": 2 * 60 + 120, "max_s": 2 * 90 + 180}


def test_FR_INT_07_estimate_range_shape_matches_contract_and_is_ordered(repo_root, registry):
    units = [_unit("U1", "quote_extracted"), _unit("U2", "summary_written")]

    estimate = estimate_units(units, history=_HISTORY)

    assert_valid_credit_range(repo_root, registry, estimate["credits"])
    assert_valid_time_range(repo_root, registry, estimate["time"])
    assert estimate["credits"]["min"] <= estimate["credits"]["max"]
    assert estimate["time"]["min_s"] <= estimate["time"]["max_s"]


def test_FR_INT_07_unknown_unit_type_refuses_rather_than_guessing():
    units = [_unit("U1", "quote_extracted"), _unit("U2", "never_seen_before")]

    try:
        estimate_units(units, history=_HISTORY)
        raised = False
    except UnknownUnitTypeError:
        raised = True

    assert raised, "an estimate must never silently guess a missing unit type's cost"


def test_FR_INT_07_no_model_or_network_import_in_estimate(repo_root: pathlib.Path):
    """FR-INT-07: "the model never supplies the numbers" -- estimate.py is plain arithmetic."""
    path = repo_root / "packages" / "planning" / "src" / "tilo_planning" / "estimate.py"
    assert path.is_file(), "tilo_planning/estimate.py must exist once FR-INT-07 is implemented"
    forbidden = {"tilo_providers", "random", "secrets", "requests", "httpx", "urllib", "socket"}
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module.split(".")[0])
    bad = forbidden & found
    assert not bad, f"tilo_planning/estimate.py must not import {bad}: estimates are deterministic code"
