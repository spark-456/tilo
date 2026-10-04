"""FR-WLD-01, CL-INT-6, WE-06, WE-09, WE-11: the layout solver is deterministic, schema-valid at every tier size,
non-overlapping, and draws roads for exactly the plan's cross-building dependencies."""

from __future__ import annotations

import copy
import json
import pathlib
import random

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from tilo_world import SOLVER_VERSION, SolverError, solve

CONTRACTS = pathlib.Path(__file__).resolve().parents[3] / "contracts"
VALID = CONTRACTS / "fixtures" / "layout" / "valid"


def _validator() -> Draft202012Validator:
    docs = [json.loads(p.read_text(encoding="utf-8")) for p in CONTRACTS.glob("**/*.schema.json")]
    registry = Registry().with_resources([(d["$id"], Resource.from_contents(d)) for d in docs])
    return Draft202012Validator(json.loads((CONTRACTS / "layout.schema.json").read_text("utf-8")), registry=registry)


def errors(semantic: dict, geometry: dict) -> list[str]:
    layout = {"v": "1.0", "world_id": "w_t", "tier": "village", "theme": "metropolis", "semantic": semantic}
    return [e.message for e in _validator().iter_errors({**layout, "geometry": geometry})]


def make_semantic(levels: int, districts: int, per_district: int, islands: int = 2) -> tuple[dict, list]:
    """Levels x districts x buildings, one unit per building; a dependency chain through every building and the
    first building of each district also depending on the previous level's first one."""
    unit, lvls, units = 0, [], []
    for lv in range(levels):
        ds = []
        for d in range(districts):
            blds = []
            for b in range(per_district):
                unit += 1
                units.append(f"U{unit}")
                blds.append({"id": f"B{unit}", "name": f"Bay {unit}", "kind": "common", "common_type": "workshop",
                             "plan_units": [f"U{unit}"]})  # fmt: skip
            ds.append({"id": f"D{lv * districts + d + 1}", "name": f"District {d + 1}", "icon": "inbox",
                       "lead": "A_l1", "buildings": blds})  # fmt: skip
        lvls.append({"id": f"L{lv + 1}", "name": f"Level {lv + 1}", "districts": ds})
    isl = [{"id": f"I{n}", "name": f"Island {n}", "conn": "api", "bridge": "road", "state": "connected"}
           for n in range(1, islands + 1)]  # fmt: skip
    first = lambda i: lvls[i]["districts"][0]["buildings"][0]["id"]  # noqa: E731
    gates = [{"id": f"G{n}", "guards": "send_email", "between": [first(n % levels), f"I{n}"], "policy_ref": None}
             for n in range(1, islands + 1)]  # fmt: skip
    sem = {"levels": lvls, "islands": isl, "gates": gates, "agents": [{"id": "A_dir", "rank": "director"}]}
    return sem, [(a, b) for a, b in zip(units, units[1:], strict=False)]


SIZES = {"outpost": (1, 1, 2, 0), "village": (1, 2, 3, 2), "town": (1, 4, 4, 3), "crowd": (3, 6, 5, 4)}


@pytest.mark.parametrize("tier", SIZES)
def test_FR_WLD_01_CL_INT_6_solved_geometry_is_schema_valid_per_tier(tier):
    semantic, edges = make_semantic(*SIZES[tier])
    geometry = solve(semantic, SOLVER_VERSION, edges)
    assert errors(semantic, geometry) == []
    assert geometry["solver_version"] == SOLVER_VERSION


def test_FR_WLD_01_CL_INT_6_contract_fixtures_solve_valid():
    for name in ("village_semantic_only", "village_basic", "village_solved"):
        layout = json.loads((VALID / f"{name}.json").read_text(encoding="utf-8"))
        assert errors(layout["semantic"], solve(layout["semantic"], "1.0.0")) == [], name


def test_FR_WLD_01_CL_INT_6_same_input_gives_identical_geometry_and_key_order_does_not_matter():
    semantic, edges = make_semantic(2, 3, 3)
    first = solve(semantic, SOLVER_VERSION, edges)
    assert solve(copy.deepcopy(semantic), SOLVER_VERSION, list(edges)) == first

    def shuffled(node):
        if isinstance(node, dict):
            keys = list(node)
            random.Random(7).shuffle(keys)
            return {k: shuffled(node[k]) for k in keys}
        return [shuffled(x) for x in node] if isinstance(node, list) else node

    again = solve(shuffled(semantic), SOLVER_VERSION, list(reversed(edges)))
    assert json.dumps(again) == json.dumps(first)  # same bytes, not just equal


def test_FR_WLD_01_CL_INT_6_buildings_never_overlap_and_stay_on_their_plate():
    semantic, edges = make_semantic(3, 6, 5)
    geometry = solve(semantic, SOLVER_VERSION, edges)
    plates = {lv["id"]: lv["plate"] for lv in geometry["levels"]}
    level_of = {b["id"]: lv["id"] for lv in semantic["levels"] for d in lv["districts"] for b in d["buildings"]}
    cells = [(level_of[b["id"]], b["footprint"]) for b in geometry["buildings"]]
    assert len(cells) == 90
    for i, (la, a) in enumerate(cells):
        plate = plates[la]
        assert a["x"] + a["w"] <= plate["w"] and a["y"] + a["d"] <= plate["d"]
        for lb, b in cells[i + 1 :]:
            if la == lb:
                apart = a["x"] + a["w"] <= b["x"] or b["x"] + b["w"] <= a["x"]
                apart = apart or a["y"] + a["d"] <= b["y"] or b["y"] + b["d"] <= a["y"]
                assert apart, (a, b)
    for island in geometry["islands"]:  # islands stay off the buildings' area and on the plate
        plate, plot = plates[island["level"]], island["plot"]
        assert plot["x"] + plot["w"] <= plate["w"] and plot["y"] + plot["d"] <= plate["d"]
        assert all(plot["x"] >= d["plot"]["x"] + d["plot"]["w"] for d in geometry["districts"])


def test_FR_WLD_01_CL_INT_6_roads_equal_cross_building_dependencies_and_tints_are_district_roles():
    semantic, _ = make_semantic(1, 2, 2)
    # B1 -> B2 (cross), B1 -> B1 never, B2 -> B3 (cross), B1 -> B2 again (one road), B4 -> B1 (backwards)
    edges = [("U1", "U2"), ("U2", "U3"), ("U1", "U2"), ("U4", "U1")]
    geometry = solve(semantic, SOLVER_VERSION, edges)
    assert [(r["from"], r["to"]) for r in geometry["roads"]] == [("B1", "B2"), ("B2", "B3"), ("B4", "B1")]
    assert all(len(r["path"]) >= 2 for r in geometry["roads"])
    assert [d["tint"] for d in geometry["districts"]] == ["district.1", "district.2"]
    assert solve(semantic, SOLVER_VERSION, [])["roads"] == []


def test_FR_WLD_01_CL_INT_6_same_building_dependency_makes_no_road():
    semantic, _ = make_semantic(1, 1, 1)
    semantic["levels"][0]["districts"][0]["buildings"][0]["plan_units"] = ["U1", "U2"]
    assert solve(semantic, SOLVER_VERSION, [("U1", "U2")])["roads"] == []


@pytest.mark.parametrize(
    "mutate",
    [
        lambda s: s["levels"][0]["districts"][0]["buildings"].append(s["levels"][0]["districts"][0]["buildings"][0]),
        lambda s: s["gates"][0].update(between=["B999", "I1"]),
        lambda s: s["gates"][0].update(between=["B1", "I999"]),
        lambda s: s["levels"][0]["districts"].extend([copy.deepcopy(s["levels"][0]["districts"][0])] * 7),
        lambda s: s["islands"].append(copy.deepcopy(s["islands"][0])),
        lambda s: s.pop("levels"),
        lambda s: s["levels"][0]["districts"][0]["buildings"][0].pop("plan_units"),
    ],
)
def test_FR_WLD_01_CL_INT_6_malformed_semantic_raises_value_error_or_key_error(mutate):
    semantic, _ = make_semantic(1, 1, 2)
    mutate(semantic)
    with pytest.raises((SolverError, KeyError, TypeError)):
        solve(semantic, SOLVER_VERSION)


def test_FR_WLD_01_CL_INT_6_unknown_dependency_unit_and_version_are_refused():
    semantic, _ = make_semantic(1, 1, 2)
    with pytest.raises(SolverError):
        solve(semantic, SOLVER_VERSION, [("U1", "U404")])
    with pytest.raises(SolverError):
        solve(semantic, "9.9.9")
