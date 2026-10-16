"""GEN-06: deterministic visual teams, using existing contract worker ranks."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[4]


def with_design_team(units: list[dict[str, Any]], brief: dict[str, Any]) -> list[dict[str, Any]]:
    config = yaml.safe_load((ROOT / "config/deliverable_teams.yaml").read_text(encoding="utf-8"))
    limits = yaml.safe_load((ROOT / "config/tool_loop.yaml").read_text(encoding="utf-8"))["design"]
    if limits["revision_rounds"] not in (0, 1):
        raise ValueError("design.revision_rounds must be zero or one")
    if any(u["unit_type"].startswith("design_") for u in units):
        return units
    items = brief.get("deliverables", [])
    result = copy.deepcopy(units)
    number = max(int(u["id"][1:]) for u in units) + 1
    for writer in list(result):
        if writer["unit_type"] != "deliver" or writer["role"] != "writer":
            continue
        own = items if len(items) == 1 else [i for i in items if i.get("title", "").strip()[:80] == writer["title"]]
        if len(own) != 1 or own[0].get("format") not in config["formats"]:
            continue
        stages: dict[str, str] = {}
        team: list[dict[str, Any]] = []
        for stage in config["stages"]:
            if stage.get("revision") and not limits["revision_rounds"]:
                continue
            ident = f"U{number}"
            number += 1
            team.append(
                {
                    "id": ident,
                    "unit_type": stage["type"],
                    "title": stage["title"],
                    "role": stage["role"],
                    "district": writer["district"],
                    "skills": [],
                    "connectors": [],
                    "actions": [],
                    "depends_on": [stages[s] for s in stage["after"]] or list(writer["depends_on"]),
                }
            )
            stages[stage["type"]] = ident
        writer["depends_on"] = list(dict.fromkeys([*writer["depends_on"], *stages.values()]))
        result[result.index(writer) : result.index(writer)] = (
            team  # designers, reviewer, revisers, then the deliver unit
        )
    return result
