"""FR-INT-03 / FR-CON-10 / BQ-218 (issue #283): every plan ends in a deliver unit, so a completed run delivers at
least one artifact in Tilo (in_app, ungated). The unit is added by code after the Director's units, never asked of
the model (a model never decides what is delivered or gated), and it adds no gate: sending and saving stay gated."""

from __future__ import annotations

import copy
import json
import pathlib

import pytest
from _planning_contracts_lib import ScriptedCall
from test_FR_INT_09_plan_compilation import OWNER, _compile, _inputs, _reply, _units
from tilo_planning.compiler import MAX_UNITS, PlanCompileError
from tilo_planning.plangraph import validate_plan

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]


def _report_units() -> list[dict]:
    """A research-and-report shape: nothing in it sends or saves (the 9 zero-deliverable bank cases)."""
    units = _units()[:3]
    for unit in units:
        unit["actions"], unit["connectors"] = [], []
    return units


def _valid(plan: dict) -> list:
    inputs = _inputs()
    return validate_plan(
        plan, risk_table=inputs.risk_table, connectors=inputs.connectors, skills=frozenset(inputs.skills),
        policies=inputs.policies, owner=OWNER,
    )  # fmt: skip


def test_FR_INT_03_a_report_plan_ends_in_one_deliver_unit_that_adds_no_gate(tmp_path):
    directors = _report_units()

    result, _ = _compile(tmp_path, [_reply(copy.deepcopy(directors))])

    plan = result.plan
    assert plan["units"][:3] == directors, "the Director's units come first, unchanged"
    *_, deliver = plan["units"]
    assert len(plan["units"]) == 4
    assert (deliver["unit_type"], deliver["role"]) == ("deliver", "writer")
    assert (deliver["actions"], deliver["connectors"], deliver["skills"]) == ([], [], [])
    assert deliver["depends_on"] == ["U3"], "it waits for the units nothing else waits for"
    assert deliver["district"] in {u["district"] for u in directors}
    assert plan["gates"] == [], "delivering in Tilo is no side effect: no gate"
    assert _valid(plan) == []


def test_FR_INT_03_the_deliver_unit_waits_for_every_leaf_of_a_branching_plan(tmp_path):
    units = _report_units()
    units[2]["depends_on"] = ["U1"]  # U2 and U3 both hang off U1: two leaves

    result, _ = _compile(tmp_path, [_reply(units)])

    *_, deliver = result.plan["units"]
    assert deliver["depends_on"] == ["U2", "U3"]
    assert _valid(result.plan) == []


def test_FR_INT_03_a_plan_with_a_send_keeps_its_gate_and_still_delivers_in_tilo(tmp_path):
    result, _ = _compile(tmp_path, [_reply(_units())])  # U1..U4, U4 sends by email

    plan = result.plan
    (gate,) = plan["gates"]
    assert (gate["action_type"], gate["guards"]) == ("send_email", ["U4"])
    *_, deliver = plan["units"]
    assert deliver["unit_type"] == "deliver" and deliver["depends_on"] == ["U4"] and deliver["actions"] == []
    assert _valid(plan) == []


def test_FR_INT_03_the_model_does_not_choose_the_deliver_unit(tmp_path):
    units = _report_units()
    ours = {**units[2], "id": "U4", "unit_type": "deliver", "title": "Deliver", "depends_on": ["U3"]}

    result, _ = _compile(tmp_path, [_reply([*units, ours])])  # a Director that names its own deliver unit

    assert [u["unit_type"] for u in result.plan["units"]].count("deliver") == 1, "never two"
    assert _valid(result.plan) == []


def test_FR_INT_03_the_deliver_unit_fits_under_the_unit_limit(tmp_path):
    base = _units()[0]
    chain = [{**base, "id": f"U{n}", "depends_on": [f"U{n - 1}"] if n > 1 else [], "actions": [], "connectors": []}
             for n in range(1, MAX_UNITS)]  # fmt: skip

    result, _ = _compile(tmp_path, [_reply(chain)])

    assert len(result.plan["units"]) == MAX_UNITS and result.plan["units"][-1]["unit_type"] == "deliver"
    assert _valid(result.plan) == []


def test_FR_INT_03_the_director_is_told_the_deliver_unit_is_added_for_it():
    prompt = (REPO_ROOT / "prompts" / "director" / "plan_system.md").read_text(encoding="utf-8")
    assert "deliver" in prompt.lower(), "the Director is told the deliver unit is added for it"
    assert json.dumps(MAX_UNITS - 1) in prompt, "and that its own units stop one short of the limit"


def test_FR_INT_03_a_director_reply_of_the_full_limit_leaves_no_room_for_deliver(tmp_path):
    many = [{**_units()[0], "id": f"U{n}", "actions": [], "connectors": []} for n in range(1, MAX_UNITS + 1)]
    reply = ScriptedCall(text=json.dumps({"units": many}))

    with pytest.raises(PlanCompileError, match="FR-INT-09"):  # no room for the deliver unit: plan fewer
        _compile(tmp_path, [reply] * 3)
