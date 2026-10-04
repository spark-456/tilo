"""The deterministic layout solver (FR-WLD-01, PRD 9.1; contracts/layout.rules.md WE-06, WE-09, WE-11).

`solve(semantic, solver_version, edges)` is a pure function: no randomness, no clock, no I/O, standard library
only. Everything is placed on an integer grid in the order the semantic part lists it, so the same input always
gives the same geometry, whatever the key order of the input dicts.

Per level (a plate): districts are rows, 5 grid rows apart; a district plot is 4 deep with its buildings (2 x 2)
3 cells apart, so row `y + 3` (south of the buildings) and column 0 are free "streets". Islands sit east of the
plate, 3 x 3, 4 rows apart. Roads and bridges only run along the streets, never across a building."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

SOLVER_VERSION = "1.0.0"
_ROW, _PLOT_D, _PITCH, _SIDE, _ISLAND, _ISLAND_PITCH, _GAP = 5, 4, 3, 2, 3, 4, 2
_MAX_DISTRICTS = 6


class SolverError(ValueError):
    """The semantic part cannot be laid out (unsupported version, duplicate ids, unresolved references)."""


def _rect(x: int, y: int, w: int, d: int) -> dict[str, int]:
    return {"x": x, "y": y, "w": w, "d": d}


def _pt(x: int, y: int) -> dict[str, int]:
    return {"x": x, "y": y}


def _path(*points: tuple[int, int]) -> list[dict[str, int]]:
    """Points with consecutive repeats dropped (a path always keeps at least two points)."""
    kept: list[tuple[int, int]] = []
    for p in points:
        if not kept or kept[-1] != p:
            kept.append(p)
    if len(kept) < 2:
        kept.append(kept[0])
    return [_pt(*p) for p in kept]


def solve(
    semantic: Mapping[str, Any], solver_version: str = SOLVER_VERSION, edges: Iterable[tuple[str, str]] = ()
) -> dict[str, Any]:
    """`geometry` for `semantic` (layout.schema.json `$defs.geometry`).

    `edges` are plan dependencies as (dependency unit id, dependant unit id); each one between units in different
    buildings becomes one road from the dependency's building to the dependant's, once per building pair (WE-06).
    The semantic part carries no dependencies, so the caller derives `edges` from the plan.
    Raises SolverError (a ValueError) on input it cannot place."""
    if solver_version != SOLVER_VERSION:
        raise SolverError("unsupported solver version")
    levels_out: list[dict[str, Any]] = []
    districts_out: list[dict[str, Any]] = []
    buildings_out: list[dict[str, Any]] = []
    bridges_out: list[dict[str, Any]] = []
    gates_out: list[dict[str, Any]] = []
    cells: dict[str, tuple[int, int, int, int]] = {}  # building -> x, y, w, d
    level_of: dict[str, str] = {}  # building -> level id
    unit_building: dict[str, str] = {}
    order: dict[str, int] = {}  # building -> position in the semantic order
    plates: list[tuple[str, int, int, int]] = []  # level id, index, width of the building area, district rows

    for index, level in enumerate(semantic["levels"]):
        districts = level["districts"]
        if not 0 < len(districts) <= _MAX_DISTRICTS:
            raise SolverError("a level holds 1 to 6 districts")
        width = 1 + _PITCH * max(len(d["buildings"]) for d in districts)
        for row, district in enumerate(districts):
            y = _ROW * row
            plot = _rect(0, y, width, _PLOT_D)
            districts_out.append({"id": district["id"], "plot": plot, "tint": f"district.{row + 1}"})
            for col, b in enumerate(district["buildings"]):
                if b["id"] in cells:
                    raise SolverError("duplicate building id")
                cells[b["id"]] = (1 + _PITCH * col, y + 1, _SIDE, _SIDE)
                level_of[b["id"]], order[b["id"]] = level["id"], len(order)
                units = list(b["plan_units"])
                for u in units:
                    if u in unit_building:
                        raise SolverError("a unit is in two buildings")
                    unit_building[u] = b["id"]
                floors = min(4, 1 + max(0, len(units) - 1) // 2)
                buildings_out.append({"id": b["id"], "footprint": _rect(*cells[b["id"]]), "floors": floors})
        plates.append((level["id"], index, width, len(districts)))

    first_level = plates[0][0]
    island_ids = [i["id"] for i in semantic["islands"]]
    if len(set(island_ids)) != len(island_ids):
        raise SolverError("duplicate island id")
    island_level: dict[str, str] = {}  # the level of the first building whose gate reaches it, else the first level
    bridge_keys: list[tuple[str, str]] = []  # (island, building): one bridge per gate pair, then one per lone island
    for gate in semantic["gates"]:
        building, island = gate["between"][0], gate["between"][1]
        if building not in cells or island not in island_ids:
            raise SolverError("a gate points at nothing")
        island_level.setdefault(island, level_of[building])
        if (island, building) not in bridge_keys:
            bridge_keys.append((island, building))
    for island_id in island_ids:
        if island_id not in island_level:
            island_level[island_id] = first_level
            bridge_keys.append((island_id, next(b for b in order if level_of[b] == first_level)))

    plot_of: dict[str, tuple[int, int, int, int]] = {}
    width_of = {p[0]: p[2] for p in plates}
    for level_id, index, width, rows in plates:
        ids = [i for i in island_ids if island_level[i] == level_id]
        for k, island_id in enumerate(ids):
            plot_of[island_id] = (width + _GAP, _ISLAND_PITCH * k, _ISLAND, _ISLAND)
        w = width + (_GAP + _ISLAND if ids else 0)
        d = max(_ROW * rows - 1, _ISLAND_PITCH * len(ids) - 1)
        levels_out.append({"id": level_id, "index": index, "plate": _rect(0, 0, w, d)})
    islands_out = [{"id": i, "level": island_level[i], "plot": _rect(*plot_of[i])} for i in island_ids]

    first_leg: dict[tuple[str, str], tuple[int, int, int]] = {}  # (island, building) -> mid x, y, lane x
    for island_id, building in bridge_keys:
        bx, by, bw, bd = cells[building]
        px, py = plot_of[island_id][:2]
        sx, sy, lane = bx + bw - 1, by + bd, width_of[level_of[building]] + 1
        path = _path((sx, sy), (lane, sy), (lane, py + 1), (px, py + 1))
        bridges_out.append({"island": island_id, "from": building, "path": path})
        first_leg[(island_id, building)] = ((sx + lane) // 2, sy, lane)
    taken: dict[tuple[str, str], int] = {}
    for gate in semantic["gates"]:
        key = (gate["between"][1], gate["between"][0])
        (mx, my, lane), n = first_leg[key], taken.get(key, 0)
        taken[key] = n + 1
        gates_out.append({"id": gate["id"], "cell": _pt(min(mx + n, lane), my)})

    pairs: dict[tuple[str, str], None] = {}
    for dep, unit in edges:
        a, b = unit_building.get(dep), unit_building.get(unit)
        if a is None or b is None:
            raise SolverError("a dependency names a unit no building holds")
        if a != b:
            pairs[(a, b)] = None
    roads_out = []
    for a, b in sorted(pairs, key=lambda p: (order[p[0]], order[p[1]])):
        (ax, ay, _, ad), (bx, by, _, bd) = cells[a], cells[b]
        start, end = (ax, ay + ad), (bx + 1, by + bd)
        via = [] if start[1] == end[1] else [(0, start[1]), (0, end[1])]
        roads_out.append({"from": a, "to": b, "path": _path(start, *via, end)})

    return {
        "solver_version": solver_version,
        "levels": levels_out,
        "districts": districts_out,
        "buildings": buildings_out,
        "islands": islands_out,
        "roads": roads_out,
        "bridges": bridges_out,
        "gates": gates_out,
    }
