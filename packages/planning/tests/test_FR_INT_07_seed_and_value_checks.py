"""FR-INT-07 (PRD 7.1, 7.3): the shipped seed table and the value checks behind `estimate_units`.

`test_FR_INT_07_estimate_arithmetic.py` covers the arithmetic with an explicit history. This file covers
the default path (the package's `unit_cost_seed.json`, empty at launch per PRD 7.3) and the refusals: a
table not marked as a seed, a range whose minimum is above its maximum, and costs that are not finite,
non-negative credits or non-negative whole seconds.
"""

from __future__ import annotations

import json
import math
import types

import pytest
from tilo_planning import estimate
from tilo_planning.estimate import UnitCost, UnknownUnitTypeError, estimate_units, load_seed_history


def _unit(unit_type: str) -> dict:
    return {"id": "U1", "unit_type": unit_type}


def _seed_at(monkeypatch, tmp_path, table: dict) -> None:
    """Point the module's package-resource lookup at a seed file written under tmp_path."""
    (tmp_path / estimate.SEED_FILE).write_text(json.dumps(table), encoding="utf-8")
    monkeypatch.setattr(estimate, "resources", types.SimpleNamespace(files=lambda _package: tmp_path))


def test_FR_INT_07_shipped_seed_is_marked_seed_and_empty_at_launch():
    assert load_seed_history() == {}


def test_FR_INT_07_default_history_refuses_any_unit_type_while_the_seed_is_empty():
    assert estimate_units([]) == {"credits": {"min": 0, "max": 0}, "time": {"min_s": 0, "max_s": 0}}
    with pytest.raises(UnknownUnitTypeError, match="FR-INT-07"):
        estimate_units([_unit("research")])


def test_FR_INT_07_a_filled_seed_drives_the_default_estimate(monkeypatch, tmp_path):
    row = {"credits_min": 1.5, "credits_max": 2.5, "time_min_s": 30, "time_max_s": 90}
    _seed_at(monkeypatch, tmp_path, {"seed": True, "unit_types": {"research": row}})

    assert load_seed_history() == {"research": UnitCost(**row)}
    assert estimate_units([_unit("research"), _unit("research")]) == {
        "credits": {"min": 3.0, "max": 5.0},
        "time": {"min_s": 60, "max_s": 180},
    }


@pytest.mark.parametrize("seed_flag", [False, None, "true", 1])
def test_FR_INT_07_a_table_not_marked_as_seed_is_refused(monkeypatch, tmp_path, seed_flag):
    table = {"unit_types": {}} if seed_flag is None else {"seed": seed_flag, "unit_types": {}}
    _seed_at(monkeypatch, tmp_path, table)
    with pytest.raises(ValueError, match="must be marked as a seed"):
        load_seed_history()


@pytest.mark.parametrize(
    "row",
    [
        {"credits_min": 3, "credits_max": 2, "time_min_s": 10, "time_max_s": 20},
        {"credits_min": 1, "credits_max": 2, "time_min_s": 30, "time_max_s": 20},
    ],
    ids=["credits", "time"],
)
def test_FR_INT_07_a_seed_range_with_min_above_max_is_refused(monkeypatch, tmp_path, row):
    _seed_at(monkeypatch, tmp_path, {"seed": True, "unit_types": {"research": row}})
    with pytest.raises(ValueError, match="minimum is above its maximum"):
        load_seed_history()


def test_FR_INT_07_a_bad_seed_value_is_refused_while_loading(monkeypatch, tmp_path):
    row = {"credits_min": -1, "credits_max": 2, "time_min_s": 10, "time_max_s": 20}
    _seed_at(monkeypatch, tmp_path, {"seed": True, "unit_types": {"research": row}})
    with pytest.raises(ValueError, match="credits must be finite and non-negative"):
        load_seed_history()


@pytest.mark.parametrize("bad", [-0.01, math.nan, math.inf, "1"], ids=["negative", "nan", "inf", "string"])
def test_FR_INT_07_credits_must_be_finite_and_non_negative(bad):
    history = {"research": UnitCost(credits_min=bad, credits_max=2.0, time_min_s=1, time_max_s=2)}
    with pytest.raises(ValueError, match="'research' credits must be finite and non-negative"):
        estimate_units([_unit("research")], history=history)


@pytest.mark.parametrize("bad", [-1, 1.5, True, "10"], ids=["negative", "fraction", "bool", "string"])
def test_FR_INT_07_times_must_be_non_negative_whole_seconds(bad):
    history = {"research": UnitCost(credits_min=1.0, credits_max=2.0, time_min_s=0, time_max_s=bad)}
    with pytest.raises(ValueError, match="'research' times must be non-negative whole seconds"):
        estimate_units([_unit("research")], history=history)
