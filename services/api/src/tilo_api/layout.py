"""The default layout builder for a run (CL-INT-2, PRD 9.1, 9.3; services/api/tests/API_CL_INT_2.md): plain
code, no model. One level; one Director; per district a Lead and a workshop holding its units; one worker per
unit by role; one island per connector the plan uses; one gate per plan gate, between the guarded unit's
workshop and its connector's island. Geometry is the solver's (null here)."""

from __future__ import annotations

from typing import Any

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
    for n, district_id in enumerate(district_ids, start=1):
        agents.append({"id": f"A_lead{n}", "rank": "lead"})
        members = [unit["id"] for unit in units if unit["district"] == district_id]
        building_of |= dict.fromkeys(members, f"B{n}")
        workshop = {"id": f"B{n}", "name": "Workshop", "kind": "common", "common_type": "workshop"}
        districts.append(
            {
                "id": district_id,
                "name": f"Workstream {n}",
                "icon": "inbox",
                "lead": f"A_lead{n}",
                "buildings": [{**workshop, "plan_units": members}],
            }
        )

    connector_ids = sorted({c for unit in units for c in unit["connectors"]})
    island_of = {c: f"I{n}" for n, c in enumerate(connector_ids, start=1)}
    islands = [
        {"id": island, "name": f"Connector {island[1:]}", "conn": "api", "bridge": "road", "state": "connected"}
        for island in island_of.values()
    ]
    gates = []
    for gate in plan["gates"]:
        unit = next((u for u in units if u["id"] in gate["guards"] and u["connectors"]), None)
        if unit is not None:
            between = [building_of[unit["id"]], island_of[unit["connectors"][0]]]
            gates.append(
                {"id": gate["id"], "guards": gate["action_type"], "between": between, "policy_ref": gate["policy_ref"]}
            )
    return {
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
