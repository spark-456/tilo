"""The default layout builder for a run (CL-INT-2, PRD 9.1, 9.3; services/api/tests/API_CL_INT_2.md): plain
code, no model. One level; one Director; per district a Lead and a workshop holding its units; one worker per
unit by role; one island per connector the plan uses; one gate per plan gate, between the guarded unit's
workshop and its connector's island. Geometry is the solver's (null here)."""

from __future__ import annotations

from typing import Any

_WORKER_PREFIX = {"specialist": "A_s", "writer": "A_w", "verifier": "A_v"}


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
