"""The default layout builder for a run (CL-INT-2, PRD 9.1, 9.3; services/api/tests/API_CL_INT_2.md): plain
code, no model. One level; one Director; per district a Lead and one building per unit of work, named from the
unit's plan title (WORLD-LIVE: a district of more than three units shares them out), a Meeting Hall in the first
district and a Delivery Dock in the last; one worker per unit by role; one island per connector the plan uses; one
gate per plan gate, between the guarded unit's building and its connector's island. Geometry is the solver's
(CL-INT-6, `tilo_world.solve`, FR-WLD-01): attached only after the whole layout validates against
layout.schema.json; on any solver or schema failure it stays null."""

from __future__ import annotations

import functools
import json
import logging
import re
from pathlib import Path
from typing import Any

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012
from tilo_world import SOLVER_VERSION, solve

CONTRACTS = Path(__file__).resolve().parents[4] / "contracts"
_log = logging.getLogger(__name__)

_WORKER_PREFIX = {"specialist": "A_s", "writer": "A_w", "verifier": "A_v"}


def visible_layout(layout: dict[str, Any], districts: tuple[str, ...]) -> dict[str, Any] | None:
    """A non-owner's view of a layout (PRD 10.1), built from an allowlist of layout.schema.json's keys, never by
    copying a stored record forward: only the districts in `districts` with their levels and buildings; the
    gates that start in a visible building and the islands they reach; and the agents the layout itself ties to
    what is visible: the Director, the Narrator and the Leads of visible districts (a Lead shared with a hidden
    district stays for the visible one). A worker is never listed, since the layout ties none to a unit, and no
    `team_lead` is ever returned. `geometry` is null (it places hidden districts). None when nothing is visible
    or the stored layout is malformed: both are a 404, never a 500 and never a partial leak."""
    try:
        return _visible_layout(layout, districts)
    except (KeyError, TypeError, AttributeError, IndexError):
        return None


def _pick(record: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {k: record[k] for k in keys if k in record}


def _visible_layout(layout: dict[str, Any], districts: tuple[str, ...]) -> dict[str, Any] | None:
    semantic = layout["semantic"]
    levels, buildings, leads = [], set(), set()
    for level in semantic["levels"]:
        kept = []
        for district in level["districts"]:
            if district["id"] not in districts:
                continue
            leads.add(district["lead"])
            blds = []
            for b in district["buildings"]:
                buildings.add(b["id"])
                bld = _pick(b, ("id", "name", "kind", "common_type"))
                bld["plan_units"] = list(b["plan_units"])
                if "kit" in b:
                    bld["kit"] = {"icon": b["kit"]["icon"], "parts": list(b["kit"]["parts"])}
                blds.append(bld)
            kept.append({**_pick(district, ("id", "name", "icon", "lead")), "buildings": blds})
        if kept:
            levels.append({**_pick(level, ("id", "name")), "districts": kept})
    if not levels:
        return None
    gates = [
        {**_pick(g, ("id", "guards", "policy_ref")), "between": list(g["between"])}
        for g in semantic["gates"]
        if g["between"][0] in buildings
    ]
    reached = {g["between"][1] for g in gates}
    islands = [_pick(i, ("id", "name", "conn", "bridge", "state")) for i in semantic["islands"] if i["id"] in reached]
    agents = [
        _pick(a, ("id", "rank"))
        for a in semantic["agents"]
        if a["rank"] in ("director", "narrator") or (a["rank"] == "lead" and a["id"] in leads)
    ]
    return {
        **_pick(layout, ("v", "world_id", "tier", "theme")),
        "semantic": {"levels": levels, "islands": islands, "gates": gates, "agents": agents},
        "geometry": None,
    }


@functools.cache
def _validator() -> jsonschema.Draft202012Validator:
    """layout.schema.json with every contracts/**/*.schema.json registered by its $id (cross-file $refs)."""
    docs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(CONTRACTS.glob("**/*.schema.json"))]
    registry = Registry().with_resources([(d["$id"], Resource.from_contents(d, DRAFT202012)) for d in docs])
    schema = json.loads((CONTRACTS / "layout.schema.json").read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator(schema, registry=registry)


def attach_geometry(layout: dict[str, Any], plan: dict[str, Any]) -> None:
    """Set `layout["geometry"]` to the solver's result for `layout["semantic"]` and the plan's `depends_on` edges
    (WE-06), if the whole layout then validates; otherwise leave it null and log only the exception class."""
    try:
        edges = [(dep, unit["id"]) for unit in plan["units"] for dep in unit["depends_on"]]
        candidate = {**layout, "geometry": solve(layout["semantic"], SOLVER_VERSION, edges)}
        if next(iter(_validator().iter_errors(candidate)), None) is not None:
            raise ValueError("layout schema")
        layout["geometry"] = candidate["geometry"]
    except Exception as exc:  # fail closed: a world with no geometry is honest, a 500 is not
        _log.warning("layout solver failed: %s", type(exc).__name__)


_UNIT_BUILDINGS = 3  # a district holds at most 5 buildings (layout.schema.json); two are left for the hall and the dock


def _common(building_id: str, name: str, common_type: str) -> dict[str, Any]:
    """A common building no unit works in (the Meeting Hall, the Delivery Dock)."""
    return {"id": building_id, "name": name, "kind": "common", "common_type": common_type, "plan_units": []}


_COMMON_OF_ROLE = {"specialist": "workshop", "writer": "library", "verifier": "watchtower"}
_NAME_CHARS = re.compile(r"[^A-Za-z0-9 &'.,()/+-]+")


def _groups(units: list[dict[str, Any]], limit: int) -> list[list[dict[str, Any]]]:
    """The units in order, in at most `limit` runs of near-equal length (one building each when they fit)."""
    if not units:
        return []
    size = -(-len(units) // limit)
    return [units[i : i + size] for i in range(0, len(units), size)]


def _plain_name(text: str, fallback: str, *, room: int = 24) -> str:
    """A building name from a unit title: plain characters only, whole words where it can, 2-24 long (plain_name)."""
    words = _NAME_CHARS.sub(" ", text).split()
    name = ""
    for word in words:
        if len(f"{name} {word}".strip()) > room:
            break
        name = f"{name} {word}".strip()
    name = name or " ".join(words)[:room]
    name = name.strip(" &'.,/+-(")
    return name if len(name) >= 2 and name[0].isalnum() and (name[-1].isalnum() or name[-1] in ").") else fallback


def _unit_building(building_id: str, group: list[dict[str, Any]]) -> dict[str, Any]:
    """One building for a run of units, named with the first unit's plain plan title."""
    name = _plain_name(str(group[0].get("title", "")), "Workshop")
    return {
        "id": building_id,
        "name": name,
        "kind": "common",
        "common_type": _COMMON_OF_ROLE.get(group[0]["role"], "workshop"),
        "plan_units": [unit["id"] for unit in group],
    }


def _district_name(members: list[dict[str, Any]], n: int) -> str:
    """A district named for the work it holds (its first unit's plan title + " team"), never "Workstream 1"; the
    plain numbered name only when no title makes a plain one (ticket TILO-T-WORLD)."""
    name = _plain_name(str(members[0].get("title", "")), "", room=19) if members else ""
    return f"{name} team" if name else f"Workstream {n}"


def _island_name(connector: str, n: int) -> str:
    """An island named for its connector id ("google_calendar" -> "Google calendar"), else "Connector n"."""
    words = connector.replace("_", " ").strip()
    name = (words[:1].upper() + words[1:])[:24]
    return name if len(name) >= 2 and name[0].isalnum() else f"Connector {n}"


def build_layout(plan: dict[str, Any], *, world_id: str) -> dict[str, Any]:
    units = plan["units"]
    agents: list[dict[str, str]] = [{"id": "A_director", "rank": "director"}]
    counts: dict[str, int] = {}
    for unit in units:
        counts[unit["role"]] = counts.get(unit["role"], 0) + 1
    for role, prefix in _WORKER_PREFIX.items():
        agents += [{"id": f"{prefix}{n}", "rank": role} for n in range(1, counts.get(role, 0) + 1)]

    district_ids = sorted({unit["district"] for unit in units})
    building_of: dict[str, str] = {}
    districts = []
    number = 0  # buildings are numbered B1.. across the districts, in district order
    for n, district_id in enumerate(district_ids, start=1):
        agents.append({"id": f"A_lead{n}", "rank": "lead"})
        members = [unit for unit in units if unit["district"] == district_id]
        last = n == len(district_ids)
        buildings = []
        for group in _groups(members, _UNIT_BUILDINGS):
            number += 1
            building = _unit_building(f"B{number}", group)
            building_of |= dict.fromkeys(building["plan_units"], building["id"])
            buildings.append(building)
        if n == 1:  # where a person calls the team to talk (the meeting room): one labelled hall for the world
            number += 1
            buildings.append(_common(f"B{number}", "Meeting Hall", "meeting_hall"))
        if last:  # where the finished work is handed over: the one labelled delivery spot of the world
            number += 1
            buildings.append(_common(f"B{number}", "Delivery Dock", "delivery_dock"))
        districts.append(
            {
                "id": district_id,
                "name": _district_name(members, n),
                "icon": "inbox",
                "lead": f"A_lead{n}",
                "buildings": buildings,
            }
        )

    connector_ids = sorted({c for unit in units for c in unit["connectors"]})
    island_of = {c: f"I{n}" for n, c in enumerate(connector_ids, start=1)}
    islands = [
        {
            "id": island,
            "name": _island_name(conn, int(island[1:])),
            "conn": "api",
            "bridge": "road",
            "state": "connected",
        }
        for conn, island in island_of.items()
    ]
    gates = []
    for gate in plan["gates"]:
        unit = next((u for u in units if u["id"] in gate["guards"] and u["connectors"]), None)
        if unit is not None:
            between = [building_of[unit["id"]], island_of[unit["connectors"][0]]]
            gates.append(
                {"id": gate["id"], "guards": gate["action_type"], "between": between, "policy_ref": gate["policy_ref"]}
            )
    layout: dict[str, Any] = {
        "v": "1.0",
        "world_id": world_id,
        "tier": "village",
        "theme": "metropolis",
        "geometry": None,
        "semantic": {
            "levels": [{"id": "L1", "name": "Level One", "districts": districts}],
            "islands": islands,
            "gates": gates,
            "agents": agents,
        },
    }
    attach_geometry(layout, plan)
    return layout
