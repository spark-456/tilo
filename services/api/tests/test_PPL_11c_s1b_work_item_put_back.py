"""PPL-11c slice 1b: Put back, the plate's action on a parked item (ADR-0021, PE-29: `put_back` only on a `parked`
row; API_PPL_11c.md section 2). It applies to a snoozed item (the snooze is cleared) and to an item the owner asked to
reassign (the ask is withdrawn); a done item is put back with reopen. Either way one history entry `edited` is added and
the item rejoins `rows` on the next plate. Same rules as the other work-item writes: closed body, the one 404, 409 after
one attempt.
"""

from __future__ import annotations

from _ppl11a_lib import DEV, MEERA, NOW, OWNER, PRIYA, SAM, conforms, find_row, own_item
from _ppl11c_lib import R_WI_PUT_BACK, SNOOZE_OK, path_of, refusals, work_rig


def _put_back(rig, item_id: str, body=None):
    rig.require_route(R_WI_PUT_BACK)
    return rig.client.post(path_of(R_WI_PUT_BACK, work_item_id=item_id), json={} if body is None else body)


def test_PPL_11c_s1b_PE_29_putting_back_a_snoozed_item_clears_the_snooze_and_returns_it_to_rows(people_rig):
    rig = work_rig(people_rig)
    rig.add("work_items", own_item("wi_snoozed", PRIYA, snoozed_until=SNOOZE_OK))
    assert find_row(rig.plate().json(), "work_item", "wi_snoozed")[1]["group"] == "snoozed"
    before = rig.stored("work_items", "wi_snoozed")
    response = _put_back(rig, "wi_snoozed")
    assert response.status_code == 200, response.text[:300]
    stored = rig.stored("work_items", "wi_snoozed")
    assert response.json() == stored and conforms("work_item.schema.json", stored)
    assert stored["snoozed_until"] is None and stored["status"] == "open" and stored["updated_at"] == NOW
    assert stored["history"] == before["history"] + [{"at": NOW, "by": PRIYA, "change": "edited", "status": "open"}]
    assert find_row(rig.plate().json(), "work_item", "wi_snoozed")[0] == "rows"


def test_PPL_11c_s1b_PE_29_putting_back_an_asked_item_withdraws_the_ask(people_rig):
    """After `not-mine` the item is in `parked.asked`; Put back adds a later history entry (so the last change is no
    longer `reassign_requested`) and the item rejoins `rows`. Status, owner and assigner are untouched."""
    rig = work_rig(people_rig)
    assert rig.client.post("/v1/work-items/wi_rate_sheet/not-mine", json={}).status_code == 200
    assert find_row(rig.plate().json(), "work_item", "wi_rate_sheet")[1]["group"] == "asked"
    asked = rig.stored("work_items", "wi_rate_sheet")
    response = _put_back(rig, "wi_rate_sheet")
    assert response.status_code == 200, response.text[:300]
    stored = rig.stored("work_items", "wi_rate_sheet")
    assert stored["history"][-1] == {"at": NOW, "by": PRIYA, "change": "edited", "status": "open"}
    assert stored["history"][:-1] == asked["history"]
    assert (stored["status"], stored["owner"], stored["assigned_by"]) == ("open", PRIYA, asked["assigned_by"])
    assert find_row(rig.plate().json(), "work_item", "wi_rate_sheet")[0] == "rows"


def test_PPL_11c_s1b_PE_29_an_item_that_is_not_parked_is_not_put_back(people_rig):
    rig = work_rig(people_rig)
    before = rig.snapshot()
    response = _put_back(rig, "wi_own1")
    assert response.status_code == 409 and response.json()["code"] == "write_refused", response.text[:200]
    assert rig.snapshot() == before


def test_PPL_11c_s1b_PE_03_everyone_but_the_owner_gets_the_one_404_and_the_body_is_closed(people_rig):
    rig = work_rig(people_rig)
    rig.add("work_items", own_item("wi_snoozed", PRIYA, snoozed_until=SNOOZE_OK))
    before = rig.snapshot()
    seen = []
    for actor in (DEV, SAM, MEERA, OWNER, "u_ghost"):
        rig.as_user(actor)
        seen += [_put_back(rig, i) for i in ("wi_snoozed", "wi_rate_sheet", "wi_never_made", "bad_id")]
    assert {r.status_code for r in seen} == {404} and len(refusals(seen)) == 1
    rig.as_user(PRIYA)
    for body in ({"source": {"ref": "x"}}, {"status": "open"}, {"snoozed_until": None}, {"history": []}, []):
        assert _put_back(rig, "wi_snoozed", body).status_code == 422, body
    rig.conflicting_stores("work_items")
    lost = _put_back(rig, "wi_snoozed")
    assert lost.status_code == 409 and lost.json()["code"] == "version_conflict"
    assert rig.snapshot() == before
