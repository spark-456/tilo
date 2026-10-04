"""FR-WLD-01, CL-INT-6: `build_layout` attaches the deterministic solver's geometry to a run's layout, validated
against layout.schema.json (fail closed to null); the owner's `GET /worlds/{id}/layout` returns it; a scoped viewer
still gets `geometry: null` (the solver places hidden districts)."""

from __future__ import annotations

import copy
import json
import logging
import types

import pytest
from _api_lib import OWNER, WORLD, as_principal, make_principal, make_world
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from tilo_api import layout as layout_module
from tilo_api.layout import attach_geometry, build_layout


def schema_errors(repo_root, layout) -> list[str]:
    docs = [json.loads(p.read_text(encoding="utf-8")) for p in (repo_root / "contracts").glob("**/*.schema.json")]
    registry = Registry().with_resources([(d["$id"], Resource.from_contents(d)) for d in docs])
    schema = json.loads((repo_root / "contracts" / "layout.schema.json").read_text(encoding="utf-8"))
    return [e.message for e in Draft202012Validator(schema, registry=registry).iter_errors(layout)]


def make_plan(districts: int, units_per: int = 2, connectors: bool = True) -> dict:
    """districts x units_per units; each district chains its units; each district's first unit depends on the
    previous district's last; the last unit of each district sends by connector c_mock behind a gate."""
    units, gates = [], []
    for d in range(1, districts + 1):
        for k in range(1, units_per + 1):
            n = len(units) + 1
            depends = [f"U{n - 1}"] if n > 1 else []
            last = k == units_per
            units.append({"id": f"U{n}", "role": "writer" if last else "specialist", "district": f"D{d}",
                          "connectors": ["c_mock"] if last and connectors else [], "depends_on": depends})  # fmt: skip
            if last and connectors:
                gates.append({"id": f"G{d}", "action_type": "send_email", "guards": [f"U{n}"], "policy_ref": None})
    return {"units": units, "gates": gates}


@pytest.mark.parametrize("districts, units_per", [(1, 1), (2, 3), (4, 2), (6, 5)])
def test_FR_WLD_01_CL_INT_6_build_layout_attaches_schema_valid_geometry(repo_root, districts, units_per):
    layout = build_layout(make_plan(districts, units_per), world_id="w_x")
    assert layout["geometry"] is not None
    assert schema_errors(repo_root, layout) == []
    assert [b["id"] for b in layout["geometry"]["buildings"]] == [f"B{n}" for n in range(1, districts + 1)]


def test_FR_WLD_01_CL_INT_6_roads_equal_the_plans_cross_building_dependencies():
    plan = make_plan(4, 2)
    roads = [(r["from"], r["to"]) for r in build_layout(plan, world_id="w_x")["geometry"]["roads"]]
    assert roads == [
        ("B1", "B2"),
        ("B2", "B3"),
        ("B3", "B4"),
    ]  # U2->U3, U4->U5, U6->U7; same-building ones drawn nothing
    plan["units"][-1]["depends_on"].append("U1")  # a second dependency edge, backwards over the chain
    roads = [(r["from"], r["to"]) for r in build_layout(plan, world_id="w_x")["geometry"]["roads"]]
    assert roads == [("B1", "B2"), ("B1", "B4"), ("B2", "B3"), ("B3", "B4")]
    assert build_layout(make_plan(1, 3), world_id="w_x")["geometry"]["roads"] == []


def test_FR_WLD_01_CL_INT_6_the_same_plan_gives_identical_geometry_every_time():
    plan = make_plan(5, 3)
    first = build_layout(plan, world_id="w_x")
    assert json.dumps(build_layout(copy.deepcopy(plan), world_id="w_x")) == json.dumps(first)
    assert first["geometry"]["islands"] and first["geometry"]["bridges"] and len(first["geometry"]["gates"]) == 5


def test_FR_WLD_01_CL_INT_6_a_solver_failure_keeps_geometry_null_and_logs_only_the_class(caplog):
    layout = build_layout(make_plan(2), world_id="w_x")
    layout["geometry"] = None
    layout["semantic"]["levels"][0]["districts"][0]["buildings"].append(
        copy.deepcopy(layout["semantic"]["levels"][0]["districts"][0]["buildings"][0])
    )  # duplicate building id: the solver refuses
    with caplog.at_level(logging.WARNING):
        attach_geometry(layout, make_plan(2))
    assert layout["geometry"] is None
    assert [r.getMessage() for r in caplog.records] == ["layout solver failed: SolverError"]
    layout["semantic"] = "garbage"  # a malformed semantic part never raises out of attach_geometry
    attach_geometry(layout, make_plan(2))
    attach_geometry({"semantic": {}}, {"units": "x"})
    assert layout["geometry"] is None


def test_FR_WLD_01_CL_INT_6_geometry_that_fails_the_schema_is_not_stored(monkeypatch):
    monkeypatch.setattr(layout_module, "solve", lambda *a, **k: {"solver_version": "1.0.0"})
    assert build_layout(make_plan(2), world_id="w_x")["geometry"] is None


def seed(store, layout):
    store.worlds[WORLD] = make_world(owner=OWNER)
    store.runs[WORLD] = types.SimpleNamespace(layout=layout)


def test_FR_WLD_01_CL_INT_6_owner_route_returns_geometry(client, store, repo_root):
    layout = build_layout(make_plan(3), world_id=WORLD)
    seed(store, layout)
    as_principal(make_principal())
    response = client.get(f"/worlds/{WORLD}/layout")
    assert response.status_code == 200
    assert response.json() == layout
    assert response.json()["geometry"]["solver_version"] == "1.0.0"
    assert schema_errors(repo_root, response.json()) == []


def test_FR_WLD_01_CL_INT_6_scoped_viewer_still_gets_null_geometry_and_no_hidden_ids(client, store, repo_root):
    seed(store, build_layout(make_plan(3), world_id=WORLD))
    as_principal(make_principal(user_id="u_viewer", role="viewer", districts=("D2",)))
    response = client.get(f"/worlds/{WORLD}/layout")
    assert response.status_code == 200
    assert response.json()["geometry"] is None
    for hidden in ("D1", "D3", "B1", "B3", "district.1", "district.3"):
        assert hidden not in response.text, hidden


def test_FR_WLD_01_CL_INT_6_a_layout_with_malformed_semantic_is_not_a_500(client, store):
    layout = build_layout(make_plan(2), world_id=WORLD)
    layout["semantic"] = {"levels": "oops"}
    seed(store, layout)
    as_principal(make_principal(user_id="u_viewer", role="viewer", districts=("D1",)))
    assert client.get(f"/worlds/{WORLD}/layout").status_code == 404
    as_principal(make_principal())
    assert client.get(f"/worlds/{WORLD}/layout").status_code == 200  # the owner's copy is returned as stored
