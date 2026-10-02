"""FR-WLD-05, CL-INT-4 item 3: `GET /worlds/{world_id}/layout` returns the run's layout (layout.schema.json) with
GET /worlds/{id}'s authorisation (membership, else the same 404 as an unknown world) and district redaction for a
non-owner. It never invents a layout: 404 until the run has built one."""

from __future__ import annotations

import copy
import json
import types

from _api_lib import OWNER, WORLD, as_principal, make_principal, make_world
from jsonschema import Draft202012Validator
from referencing import Registry, Resource


def two_district_layout(repo_root) -> dict:
    """The contract's village layout plus a second district D2 (lead A_l2, building B6) whose gate G2 reaches I2."""
    path = repo_root / "contracts" / "fixtures" / "layout" / "valid"
    layout = json.loads((path / "village_semantic_only.json").read_text(encoding="utf-8"))
    sem = layout["semantic"]
    sem["levels"][0]["districts"].append(
        {
            "id": "D2", "name": "Second", "icon": sem["levels"][0]["districts"][0]["icon"], "lead": "A_l2",
            "buildings": [
                {"id": "B6", "name": "Shop", "kind": "common", "common_type": "workshop", "plan_units": ["U9"]}
            ],
        }
    )  # fmt: skip
    sem["agents"].append({"id": "A_l2", "rank": "lead"})
    gate = copy.deepcopy(sem["gates"][0])
    gate.update(id="G2", between=["B6", "I2"])
    sem["gates"].append(gate)
    return layout


def seed(store, layout):
    store.worlds[WORLD] = make_world(owner=OWNER)
    store.runs[WORLD] = types.SimpleNamespace(layout=layout)


def schema_errors(repo_root, layout) -> list[str]:
    contracts = repo_root / "contracts"
    registry = Registry()
    for file in contracts.glob("*.schema.json"):
        schema = json.loads(file.read_text(encoding="utf-8"))
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    schema = json.loads((contracts / "layout.schema.json").read_text(encoding="utf-8"))
    return [e.message for e in Draft202012Validator(schema, registry=registry).iter_errors(layout)]


def test_FR_WLD_05_CL_INT_4_owner_gets_the_runs_whole_layout(client, store, repo_root):
    layout = two_district_layout(repo_root)
    seed(store, layout)
    as_principal(make_principal())
    response = client.get(f"/worlds/{WORLD}/layout")
    assert response.status_code == 200
    assert response.json() == layout
    assert schema_errors(repo_root, response.json()) == []


def test_FR_WLD_05_CL_INT_4_the_response_is_a_copy_not_the_runs_own_layout(client, store, repo_root):
    layout = two_district_layout(repo_root)
    seed(store, layout)
    as_principal(make_principal())
    client.get(f"/worlds/{WORLD}/layout")
    assert store.runs[WORLD].layout == two_district_layout(repo_root)


def test_FR_WLD_05_CL_INT_4_no_layout_yet_is_404_and_nothing_is_invented(client, store, repo_root):
    store.worlds[WORLD] = make_world(owner=OWNER)
    as_principal(make_principal())
    assert client.get(f"/worlds/{WORLD}/layout").status_code == 404  # no run at all
    store.runs[WORLD] = types.SimpleNamespace(layout={})  # a run that has not laid out yet
    assert client.get(f"/worlds/{WORLD}/layout").status_code == 404
    assert store.runs[WORLD].layout == {}


def test_FR_WLD_05_CL_INT_4_unknown_world_and_non_member_are_the_same_404(client, store, repo_root):
    seed(store, two_district_layout(repo_root))
    as_principal(make_principal(world_id="w_other"))  # signed in, but a member of another world
    non_member = client.get(f"/worlds/{WORLD}/layout")
    as_principal(make_principal(world_id="w_unknown"))
    unknown = client.get("/worlds/w_unknown/layout")
    assert (non_member.status_code, unknown.status_code) == (404, 404)
    assert non_member.content == unknown.content


def test_FR_WLD_05_CL_INT_4_other_user_with_no_visible_district_gets_404(client, store, repo_root):
    seed(store, two_district_layout(repo_root))
    as_principal(make_principal(user_id="u_viewer", role="viewer", districts=()))
    assert client.get(f"/worlds/{WORLD}/layout").status_code == 404
    as_principal(make_principal(user_id=OWNER, role="viewer", districts=()))  # the owner's id, but not as owner
    assert client.get(f"/worlds/{WORLD}/layout").status_code == 404


def test_FR_WLD_05_CL_INT_4_other_user_sees_only_their_districts(client, store, repo_root):
    seed(store, two_district_layout(repo_root))
    as_principal(make_principal(user_id="u_viewer", role="viewer", districts=("D2",)))
    response = client.get(f"/worlds/{WORLD}/layout")
    assert response.status_code == 200
    view = response.json()
    sem = view["semantic"]
    assert [d["id"] for lv in sem["levels"] for d in lv["districts"]] == ["D2"]
    assert [g["id"] for g in sem["gates"]] == ["G2"]
    assert [i["id"] for i in sem["islands"]] == ["I2"]
    assert "A_l2" in {a["id"] for a in sem["agents"]} and "A_l1" not in {a["id"] for a in sem["agents"]}
    assert view["geometry"] is None
    assert schema_errors(repo_root, view) == []
    text = response.text
    for hidden in ("D1", "B1", "G1", "I1", "A_l1"):
        assert f'"{hidden}"' not in text, hidden


def test_FR_WLD_05_CL_INT_4_a_malformed_layout_value_is_404_not_500(client, store, repo_root):
    seed(store, "not a layout")
    as_principal(make_principal())
    assert client.get(f"/worlds/{WORLD}/layout").status_code == 404
