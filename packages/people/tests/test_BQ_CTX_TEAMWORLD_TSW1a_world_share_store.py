"""BQ-CTX-TEAMWORLD, slice TSW-1a (ADR-0040 decisions 1 and 3; FR-TEAM-01 to FR-TEAM-03; PE-31, PE-35): the
`world_share` record store (`PeopleStores.world_shares`), the derived id, the in-force rule and erasure.

The in-force rule is checked against the reference oracle of the contract lane (`tests/contracts/_people_lib.py`,
`share_in_force`) on every file of `contracts/fixtures/world_share/crossref/`. No model, no clock, no network.
"""

from __future__ import annotations

import copy
import json

import _ppl10_testlib as t
import pytest
from _ppl10_testlib import errors, pl, stores

SHARES = t.REPO_ROOT / "contracts" / "fixtures" / "world_share"
CROSSREF = SHARES / "crossref"
OTHER_WORLD = "w_other_plan"


def _json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _cases():
    out = []
    for kind in ("valid", "invalid"):
        for path in sorted((CROSSREF / kind).glob("*.json")):
            case = _json(path)
            if case["world_share"] is not None:
                out.append(pytest.param(case, id=f"{kind}/{path.stem}"))
    return out


def _world_share():
    import importlib

    return importlib.import_module("tilo_people.world_share")


def _directory(case):
    from tilo_people.directory import Directory

    return Directory.of(p for key, p in case["persons"].items() if isinstance(p, dict) and p.get("id") == key)


def _active():
    return _json(SHARES / "valid" / "active.json")


def _with(**override):
    record = copy.deepcopy(_active())
    record.update(override)
    return record


def test_BQ_CTX_TEAMWORLD_FR_TEAM_01_share_id_is_ws_and_the_sha256_prefix_of_world_and_team():
    ws = _world_share()
    share = _active()
    assert ws.share_id(share["world_id"], share["team"]) == share["id"]
    assert ws.share_id("w_a", "tm_x") == pl.share_id("w_a", "tm_x")
    assert ws.share_id("w_a", "tm_x") != ws.share_id("w_a", "tm_y") != ws.share_id("w_b", "tm_x")


@pytest.mark.parametrize("case", _cases())
def test_BQ_CTX_TEAMWORLD_PE_31_in_force_is_the_reference_oracle_on_every_crossref_share(case):
    ws = _world_share()
    got = ws.in_force(case["world_share"], case["world_owner"], _directory(case), case["now"])
    assert got is pl.share_in_force(case)


@pytest.mark.parametrize(
    "bad",
    [None, {}, "ws_x", [], 7, {"revoked": None}],
)
def test_BQ_CTX_TEAMWORLD_PE_31_a_malformed_share_is_not_in_force_and_never_raises(bad):
    ws = _world_share()
    case = _cases()[0].values[0]
    assert ws.in_force(bad, case["world_owner"], _directory(case), case["now"]) is False
    assert ws.in_force(case["world_share"], None, _directory(case), case["now"]) is False
    assert ws.in_force(case["world_share"], case["world_owner"], _directory(case), "not a time") is False


def test_BQ_CTX_TEAMWORLD_FR_TEAM_01_people_stores_has_a_world_shares_store_of_its_own_kind():
    one, two = stores.PeopleStores.in_memory(), stores.PeopleStores.in_memory()
    assert one.world_shares.kind == "world_share" and one.world_shares is not two.world_shares
    assert tuple(stores.INDEXES["world_share"]) == ("world_id", "team")


def test_BQ_CTX_TEAMWORLD_FR_TEAM_01_world_shares_has_no_in_memory_default_so_a_door_that_forgets_it_fails():
    fresh = stores.PeopleStores.in_memory()
    kept = {n: getattr(fresh, n) for n in ("persons", "meetings", "work_items", "pins", "mentions", "calendar")}
    with pytest.raises(TypeError):
        stores.PeopleStores(**kept)
    assert stores.PeopleStores(**kept, world_shares=fresh.world_shares).world_shares is fresh.world_shares


def test_BQ_CTX_TEAMWORLD_FR_TEAM_01_the_store_keeps_one_schema_valid_record_per_world_and_team():
    s = stores.PeopleStores.in_memory().world_shares
    share = _active()
    assert s.create(share).version == 1
    with pytest.raises(errors.AlreadyExists):
        s.create(share)  # one record per (world, team): the id is derived, so a second create collides
    for bad in (_with(role="viewer"), _with(team="u_owner"), _with(revoked=None, granted_by=None)):
        with pytest.raises(errors.PeopleInputError):
            s.create({**bad, "id": "ws_" + "1" * 32})
    assert [x.record["id"] for x in s.list(share["org_id"])] == [share["id"]]


def test_BQ_CTX_TEAMWORLD_FR_TEAM_03_shares_are_listed_by_world_and_by_team():
    s = stores.PeopleStores.in_memory().world_shares
    ws = _world_share()
    a = _active()
    b = _with(team="tm_ops", id=ws.share_id(a["world_id"], "tm_ops"))
    c = _with(world_id=OTHER_WORLD, id=ws.share_id(OTHER_WORLD, a["team"]))
    for r in (a, b, c):
        s.create(r)
    org = a["org_id"]
    assert sorted(x.record["team"] for x in s.list(org, "world_id", a["world_id"])) == ["tm_launch", "tm_ops"]
    assert [x.record["world_id"] for x in s.list(org, "team", "tm_ops")] == [a["world_id"]]
    assert s.list("org_other", "world_id", a["world_id"]) == ()
    with pytest.raises(errors.PeopleInputError):
        s.list(org, "granted_by.by", "u_owner")  # only the two indexes the rules feed


def test_BQ_CTX_TEAMWORLD_PE_35_erasing_a_person_deletes_the_shares_they_granted_and_nobody_elses():
    s = stores.PeopleStores.in_memory()
    ws = _world_share()
    riya, owner = t.person_in("u_riya"), t.person_in("u_owner")
    s.persons.create(riya)
    s.persons.create(owner)
    mine = _with(org_id=t.ORG, granted_by={"by": "u_riya", "at": t.T1})
    theirs = _with(
        org_id=t.ORG,
        world_id=OTHER_WORLD,
        id=ws.share_id(OTHER_WORLD, "tm_launch"),
        granted_by={"by": "u_owner", "at": t.T1},
    )
    revoked_by_her = _with(
        org_id=t.ORG,
        team="tm_ops",
        id=ws.share_id("w_launch_plan", "tm_ops"),
        granted_by={"by": "u_owner", "at": t.T1},
        revoked={"by": "u_riya", "at": t.T2},
    )
    for r in (mine, theirs, revoked_by_her):
        s.world_shares.create(r)
    counts = stores.erase_person(s, mine["org_id"], "u_riya")
    assert counts["world_share"] == 1 and counts["person"] == 1
    assert sorted(x.record["id"] for x in s.world_shares.list(mine["org_id"])) == sorted(
        [theirs["id"], revoked_by_her["id"]]
    )
    again = stores.erase_person(s, mine["org_id"], "u_riya")
    assert again["world_share"] == 0
