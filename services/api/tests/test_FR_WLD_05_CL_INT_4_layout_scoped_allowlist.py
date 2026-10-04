"""FR-WLD-05, CL-INT-4, SEC-07 (security round 1 on #221): a non-owner's layout is rebuilt from an allowlist, so
nothing about a hidden district (its units, its workers, a team lead, its gates) can reach the response, whatever
the stored layout holds; a malformed stored layout is a 404; a Lead shared by two
districts stays for the visible one.
"""

from __future__ import annotations

import copy
import json

import pytest
from _api_lib import WORLD, as_principal, make_principal
from test_FR_WLD_05_CL_INT_4_layout_route import schema_errors, seed, two_district_layout


def scoped(client, store, layout, districts) -> dict:
    seed(store, layout)
    as_principal(make_principal(user_id="u_viewer", role="viewer", districts=districts))
    response = client.get(f"/worlds/{WORLD}/layout")
    assert response.status_code == 200, response.text
    return response.json()


def grow_hidden_district(layout: dict, hidden: str = "D1") -> dict:
    """The same layout with more work, workers and a team lead in the hidden district: new units in its
    buildings, a new building, worker agents (one with a team_lead), a team_lead on its Lead, a new gate and island."""
    grown = copy.deepcopy(layout)
    sem = grown["semantic"]
    district = next(d for lv in sem["levels"] for d in lv["districts"] if d["id"] == hidden)
    district["buildings"][0]["plan_units"] += ["U20", "U21", "U22"]
    district["buildings"].append(
        {"id": "B7", "name": "Archive", "kind": "common", "common_type": "library", "plan_units": ["U23"]}
    )
    sem["agents"] += [
        {"id": "A_s7", "rank": "specialist", "team_lead": "tl_hidden"},
        {"id": "A_w7", "rank": "writer"},
        {"id": "A_v7", "rank": "verifier", "team_lead": "tl_hidden"},
    ]
    next(a for a in sem["agents"] if a["id"] == district["lead"])["team_lead"] = "tl_hidden"
    sem["islands"].append({"id": "I3", "name": "Hidden system", "conn": "api", "bridge": "road", "state": "connected"})
    gate = copy.deepcopy(sem["gates"][0])
    gate.update(id="G3", between=["B7", "I3"])
    sem["gates"].append(gate)
    return grown


def test_FR_WLD_05_CL_INT_4_scoped_view_is_identical_when_a_hidden_district_gains_units_workers_or_a_team_lead(
    client, store, repo_root
):
    base = two_district_layout(repo_root)
    grown = grow_hidden_district(base)
    assert grown != base
    before = scoped(client, store, base, ("D2",))
    after = scoped(client, store, grown, ("D2",))
    assert after == before
    assert json.dumps(after, sort_keys=True) == json.dumps(before, sort_keys=True)
    assert schema_errors(repo_root, after) == []


def test_FR_WLD_05_CL_INT_4_scoped_agents_are_director_narrator_and_visible_leads_only(client, store, repo_root):
    layout = two_district_layout(repo_root)
    layout["semantic"]["agents"] += [{"id": "A_n1", "rank": "narrator"}, {"id": "A_s9", "rank": "specialist"}]
    view = scoped(client, store, layout, ("D2",))
    assert [(a["id"], a["rank"]) for a in view["semantic"]["agents"]] == [
        ("A_dir", "director"),
        ("A_l2", "lead"),
        ("A_n1", "narrator"),
    ]


def test_FR_WLD_05_CL_INT_4_no_team_lead_id_reaches_a_scoped_response(client, store, repo_root):
    layout = grow_hidden_district(two_district_layout(repo_root))
    next(a for a in layout["semantic"]["agents"] if a["id"] == "A_l2")["team_lead"] = "tl_visible_lead"
    text = json.dumps(scoped(client, store, layout, ("D2",)))
    assert "team_lead" not in text and "tl_" not in text


def test_FR_WLD_05_CL_INT_4_the_scoped_view_is_an_allowlist_not_a_copy_of_the_stored_records(client, store, repo_root):
    layout = two_district_layout(repo_root)
    sem = layout["semantic"]
    district = next(d for lv in sem["levels"] for d in lv["districts"] if d["id"] == "D2")
    for record in (
        layout, sem["levels"][0], district, district["buildings"][0], sem["gates"][-1], sem["islands"][-1],
        sem["agents"][0],
    ):  # fmt: skip
        record["extra_secret"] = "hidden-count-or-name"
    district["buildings"][0]["kit"] = {"icon": "x", "parts": ["a"], "extra_secret": 1}
    layout["geometry"] = {"solver_version": "1.0.0"}
    view = scoped(client, store, layout, ("D2",))
    assert "extra_secret" not in json.dumps(view) and "hidden-count-or-name" not in json.dumps(view)
    assert view["geometry"] is None


def test_FR_WLD_05_CL_INT_4_a_lead_shared_with_a_hidden_district_stays_for_the_visible_one(client, store, repo_root):
    layout = two_district_layout(repo_root)
    sem = layout["semantic"]
    next(d for lv in sem["levels"] for d in lv["districts"] if d["id"] == "D2")["lead"] = "A_l1"  # D1 and D2 share it
    sem["agents"] = [a for a in sem["agents"] if a["id"] != "A_l2"]
    for districts in (("D2",), ("D1",), ("D1", "D2")):
        view = scoped(client, store, layout, districts)
        listed = {a["id"] for a in view["semantic"]["agents"]}
        for level in view["semantic"]["levels"]:
            for district in level["districts"]:
                assert district["lead"] in listed, (districts, district["id"])
        assert schema_errors(repo_root, view) == []


@pytest.mark.parametrize(
    "damage",
    [
        lambda s: s.pop("agents"),
        lambda s: s.__setitem__("levels", [None]),
        lambda s: s.__setitem__("levels", "levels"),
        lambda s: s["gates"].append({"id": "G9", "between": []}),
        lambda s: s["gates"].append("gate"),
        lambda s: s["levels"][0]["districts"][0].pop("buildings"),
        lambda s: s["agents"].append({"id": "A_x"}),
        lambda s: s["islands"].append(7),
    ],
)
def test_FR_WLD_05_CL_INT_4_a_malformed_stored_layout_is_404_for_a_non_owner_not_500(client, store, repo_root, damage):
    layout = two_district_layout(repo_root)
    damage(layout["semantic"])
    seed(store, layout)
    as_principal(make_principal(user_id="u_viewer", role="viewer", districts=("D1", "D2")))
    assert client.get(f"/worlds/{WORLD}/layout").status_code == 404
