"""Owner-only meeting list, using the existing people seam and meeting contract."""

import copy

import pytest
from _ppl11a_lib import PRIYA
from _ppl11c_lib import assert_gated, assert_unwired_is_503, gone_meeting, meeting_rig


def test_FR_MTG_10_list_is_owner_scoped_read_only_and_ignores_identity_query(people_rig):
    rig = meeting_rig(people_rig)
    mine = rig.stored("meetings", "mt_q4_plan")
    other = copy.deepcopy(mine)
    other.update(id="mt_other", owner=PRIYA)
    rig.add("meetings", other)
    before = rig.snapshot()
    response = rig.get("/v1/meetings", params={"owner": PRIYA, "org_id": "org_else"})
    assert response.status_code == 200
    assert response.json() == {"items": [mine], "truncated": False}
    assert response.headers["cache-control"] == "no-store"
    assert rig.snapshot() == before
    rig.as_user(PRIYA)
    assert rig.get("/v1/meetings").json() == {"items": [other], "truncated": False}


def test_FR_MTG_10_list_uses_existing_access_gate_and_unwired_refusal(people_rig):
    routes = [("GET", "/v1/meetings")]
    assert_gated(people_rig, routes)
    assert_unwired_is_503(people_rig, routes, "people_stores")


def test_FR_MTG_10_list_excludes_deleted_and_is_bounded_deterministic(people_rig):
    rig = meeting_rig(people_rig)
    mine = rig.stored("meetings", "mt_q4_plan")
    rig.real.meetings.replace(gone_meeting(mine, "deleted"), expected_version=1)
    for n in reversed(range(201)):
        row = copy.deepcopy(mine)
        row["id"] = f"mt_list_{n:03}"
        rig.add("meetings", row)
    response = rig.get("/v1/meetings")
    assert response.status_code == 200
    answer = response.json()
    assert answer["truncated"] is True
    assert [r["id"] for r in answer["items"]] == [f"mt_list_{n:03}" for n in range(200)]


@pytest.mark.parametrize("failure", ["unsigned", "missing_person", "store"])
def test_FR_MTG_10_list_fails_closed_without_record_text(people_rig, monkeypatch, failure):
    rig = meeting_rig(people_rig)
    if failure == "unsigned":
        rig.signed_in = False
    elif failure == "missing_person":
        rig.as_user("u_missing")
    else:

        def broken(*args, **kwargs):
            raise RuntimeError("Q4 planning private text")

        monkeypatch.setattr(rig.stores.meetings, "list", broken)
    response = rig.get("/v1/meetings")
    assert response.status_code == {"unsigned": 401, "missing_person": 404, "store": 503}[failure]
    assert "Q4 planning" not in response.text
    assert response.headers["cache-control"] == "no-store"
