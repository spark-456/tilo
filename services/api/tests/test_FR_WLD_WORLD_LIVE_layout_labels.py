"""WORLD-LIVE (FR-WLD-01, FR-WLD-04): a live world's buildings say what they are. `build_layout` makes one building
per unit of work, named from the unit's plan title as a plain name (layout.schema.json plain_name), keeps a district
at five buildings or fewer, and adds one labelled Delivery Dock where the finished work is handed over."""

from __future__ import annotations

import pytest
from test_FR_WLD_01_CL_INT_6_layout_geometry import schema_errors
from tilo_api.layout import build_layout


def plan_of(*titles: str, district: str = "D1") -> dict:
    return {
        "units": [
            {
                "id": f"U{n}",
                "role": "specialist",
                "district": district,
                "title": title,
                "connectors": [],
                "depends_on": [f"U{n - 1}"] if n > 1 else [],
            }  # fmt: skip
            for n, title in enumerate(titles, start=1)
        ],
        "gates": [],
    }


def buildings(layout: dict) -> list[dict]:
    return [b for level in layout["semantic"]["levels"] for d in level["districts"] for b in d["buildings"]]


def test_FR_WLD_04_WORLD_LIVE_each_unit_has_its_own_building_named_from_its_title(repo_root):
    layout = build_layout(plan_of("Find flights", "Book the hotel", "Write the itinerary"), world_id="w_x")
    assert schema_errors(repo_root, layout) == []
    work = [b for b in buildings(layout) if b["plan_units"]]
    assert [(b["name"], b["plan_units"]) for b in work] == [
        ("Find flights", ["U1"]),
        ("Book the hotel", ["U2"]),
        ("Write the itinerary", ["U3"]),
    ]


def test_FR_WLD_04_WORLD_LIVE_the_last_district_holds_a_labelled_delivery_dock(repo_root):
    layout = build_layout(plan_of("Draft the menu"), world_id="w_x")
    dock = [b for b in buildings(layout) if b["common_type"] == "delivery_dock"]
    assert [(b["name"], b["plan_units"]) for b in dock] == [("Delivery Dock", [])]
    assert layout["geometry"] is not None
    assert {b["id"] for b in layout["geometry"]["buildings"]} == {b["id"] for b in buildings(layout)}


def test_FR_WLD_04_WORLD_LIVE_the_first_district_holds_one_labelled_meeting_hall(repo_root):
    layout = build_layout(plan_of("Draft the menu"), world_id="w_x")
    hall = [b for b in buildings(layout) if b["common_type"] == "meeting_hall"]
    assert [(b["name"], b["plan_units"]) for b in hall] == [("Meeting Hall", [])]
    assert schema_errors(repo_root, layout) == []


@pytest.mark.parametrize("units", [1, 4, 5, 9, 30])
def test_FR_WLD_04_WORLD_LIVE_a_district_never_passes_five_buildings_and_every_unit_has_one(repo_root, units):
    layout = build_layout(plan_of(*[f"Task number {n}" for n in range(1, units + 1)]), world_id="w_x")
    assert schema_errors(repo_root, layout) == []
    assert all(len(d["buildings"]) <= 5 for level in layout["semantic"]["levels"] for d in level["districts"])
    held = [u for b in buildings(layout) for u in b["plan_units"]]
    assert sorted(held) == sorted(f"U{n}" for n in range(1, units + 1))  # none lost, none twice
    assert layout["geometry"] is not None


@pytest.mark.parametrize(
    "title, expected",
    [
        ("Compare the top three bakery packaging suppliers in town", "Compare the top three"),
        ("  !!Emails & replies??  ", "Emails & replies"),
        ("x", "Workshop"),  # too short to be a name: the plain fallback
        ("", "Workshop"),
        ("☃☃ snow", "snow"),
    ],
)
def test_FR_WLD_04_WORLD_LIVE_names_are_plain_and_fit_the_schema(repo_root, title, expected):
    layout = build_layout(plan_of(title), world_id="w_x")
    assert schema_errors(repo_root, layout) == []
    assert buildings(layout)[0]["name"] == expected


def test_FR_WLD_04_WORLD_LIVE_units_that_share_a_building_say_how_many_more(repo_root):
    layout = build_layout(plan_of(*[f"Step {n} of the job" for n in range(1, 9)]), world_id="w_x")
    names = [b["name"] for b in buildings(layout) if b["plan_units"]]
    assert names == ["Step 1 of the job +2", "Step 4 of the job +2", "Step 7 of the job +1"]
    assert schema_errors(repo_root, layout) == []


def test_FR_WLD_04_TILO_T_WORLD_districts_and_islands_are_named_for_their_work(repo_root):
    plan = plan_of("Compare the top three bakery suppliers", "Draft the order email")
    plan["units"][1]["connectors"] = ["google_calendar"]
    layout = build_layout(plan, world_id="w_x")
    assert schema_errors(repo_root, layout) == []
    district = layout["semantic"]["levels"][0]["districts"][0]
    assert district["name"] == "Compare the top team"
    assert [i["name"] for i in layout["semantic"]["islands"]] == ["Google calendar"]


def test_FR_WLD_04_TILO_T_WORLD_a_district_with_no_plain_title_keeps_the_numbered_name(repo_root):
    layout = build_layout(plan_of("x"), world_id="w_x")
    assert layout["semantic"]["levels"][0]["districts"][0]["name"] == "Workstream 1"
