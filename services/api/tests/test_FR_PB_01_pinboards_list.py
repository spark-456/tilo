"""Read-only pin list: existing PE-01/02 visibility, no inferred pins."""

import copy
import json

import pytest
from _ppl11a_lib import CONTRACTS, DEV, OWNER, PRIYA, SAM
from _ppl11c_lib import assert_gated, assert_unwired_is_503


def pin(name):
    return json.loads((CONTRACTS / "fixtures" / "pinboard_item" / "valid" / f"{name}.json").read_text())


def seeded(people_rig):
    rig = people_rig()
    rig.add_people()
    # The shared owner fixture is also a team member; exercise owner privilege alone.
    owner = rig.stored("persons", OWNER)
    owner["memberships"] = []
    rig.real.persons.replace(owner, expected_version=1)
    for name in ("personal_note", "team_entry_by_person", "team_proposed_by_tilo"):
        rig.add("pins", pin(name))
    return rig


@pytest.mark.parametrize(
    "actor,expected", [(PRIYA, ["pb_launch_date", "pb_priya_note"]), (DEV, ["pb_launch_date"]), (OWNER, []), (SAM, [])]
)
def test_FR_PB_01_list_preserves_personal_and_team_visibility(people_rig, actor, expected):
    rig = seeded(people_rig)
    rig.as_user(actor)
    before = rig.snapshot()
    answer = rig.get("/v1/pinboards", params={"user": PRIYA, "team": "tm_launch"})
    assert answer.status_code == 200
    assert [row["id"] for row in answer.json()["items"]] == expected
    assert answer.json()["truncated"] is False
    assert answer.headers["cache-control"] == "no-store"
    assert rig.snapshot() == before


def test_FR_PB_01_list_bounds_deduplicates_and_reflects_membership_removal(people_rig):
    rig = people_rig()
    rig.add_people()
    row = pin("personal_note")
    for n in range(201):
        item = copy.deepcopy(row)
        item["id"] = f"pb_list_{n:03}"
        rig.add("pins", item)
    rig.as_user(PRIYA)
    answer = rig.get("/v1/pinboards").json()
    assert answer["truncated"] is True
    assert [r["id"] for r in answer["items"]] == [f"pb_list_{n:03}" for n in range(200)]
    rig.add("pins", pin("team_entry_by_person"))
    rig.as_user(DEV)
    assert len(rig.get("/v1/pinboards").json()["items"]) == 1
    person = rig.stored("persons", DEV)
    person["memberships"] = []
    rig.real.persons.replace(person, expected_version=1)
    assert rig.get("/v1/pinboards").json() == {"items": [], "truncated": False}


def test_FR_PB_01_list_failed_store_and_unwired_seam_are_not_empty_success(people_rig, monkeypatch):
    rig = seeded(people_rig)
    rig.as_user(PRIYA)

    def broken(*args, **kwargs):
        raise RuntimeError("private pin body")

    monkeypatch.setattr(rig.stores.pins, "list", broken)
    answer = rig.get("/v1/pinboards")
    assert answer.status_code == 503
    assert "private pin body" not in answer.text
    assert answer.headers["cache-control"] == "no-store"
    assert_unwired_is_503(people_rig, [("GET", "/v1/pinboards")], "people_stores")


def test_FR_PB_01_list_uses_existing_sign_in_and_declaration_gate(people_rig):
    assert_gated(people_rig, [("GET", "/v1/pinboards")])


def test_FR_PB_01_tilo_personal_pin_requires_verified_source_owner(people_rig):
    rig = people_rig()
    rig.add_people()
    row = pin("personal_added_by_tilo")
    row["source"] = {"kind": "request", "ref": "req_own", "evidence": []}
    rig.add("pins", row)
    rig.as_user(OWNER)
    assert rig.get("/v1/pinboards").json()["items"] == []
    rig.owners.owners[("request", "req_own")] = OWNER
    assert rig.get("/v1/pinboards").json()["items"] == [row]
