from pathlib import Path
from types import SimpleNamespace

import yaml
from tilo_planning.compiler import _gates, _with_deliver
from tilo_policy.tiers import load_risk_table


def test_WEBSITE_MK_07_ready_canva_pick_compiles_create_design_gate():
    units = [
        {
            "id": "U1",
            "unit_type": "research",
            "title": "Prepare the deck",
            "role": "specialist",
            "district": "D1",
            "skills": [],
            "connectors": [],
            "actions": [],
            "depends_on": [],
        }
    ]
    brief = {
        "deliverables": [
            {"title": "Deck", "format": "pptx", "make_with": "connector:canva"},
            {"title": "Notes", "format": "markdown"},
        ]
    }

    planned = _with_deliver(units, brief)

    canva = next(unit for unit in planned if unit["title"] == "Deck")
    notes = next(unit for unit in planned if unit["title"] == "Notes")
    assert canva["unit_type"] == "deliver"
    assert canva["connectors"] == ["canva"]
    assert canva["actions"] == ["create_design"]
    assert notes["actions"] == [] and notes["connectors"] == []
    root = Path(__file__).resolve().parents[3]
    declaration = yaml.safe_load((root / "config" / "canva.yaml").read_text(encoding="utf-8"))[0]
    gates = _gates(
        planned,
        SimpleNamespace(
            risk_table=load_risk_table(root / "config" / "autonomy.yaml"),
            connectors={"canva": declaration},
        ),
    )
    assert gates == [
        {
            "id": "G1",
            "action_type": "create_design",
            "guards": [canva["id"]],
            "policy_ref": None,
            "risk_tier": "T3",
        }
    ]
