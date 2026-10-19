"""PPL-11c S5 follow-up (issue #560 items 1 and 2): the work-item events go only to a world that is a Desk world AND
belongs to the person who may read the record. The Desk-world seam is checked like the meeting-world maker's answer
(BQ-273): a hostile or broken answer fails closed (nothing appended, the write undone, 503 `unavailable`, no id
echoed), and `DevDeskWorlds` never takes over a Desk id that another person owns (as `desk.ensure_desk` never does)."""

from __future__ import annotations

import pytest
from _ppl11a_lib import OWNER, PRIYA, SAM, FakeDesks, u
from _ppl11c_lib import WORK_ITEM_BODY, act, emitted, item_for, meeting_rig, stamped, work_rig

UNAVAILABLE = {"detail": "unavailable"}


class _Desks(FakeDesks):
    """A Desk-world seam that answers `world_id` and says `owner` owns it, whoever is asked (a hostile or broken
    seam); `owner=None` is a seam that does not know the world."""

    def __init__(self, world_id: object, owner: str | None) -> None:
        super().__init__()
        self.world_id, self.owner = world_id, owner

    def desk_world(self, org_id: str, user_id: str) -> str:
        self.calls.append((org_id, user_id))
        return self.world_id  # type: ignore[return-value]

    def desk_owner(self, world_id: str) -> str | None:
        return self.owner


def _all_events(rig) -> list:
    return [e for events in rig.event_store.events.values() for e in events]


HOSTILE = [
    pytest.param("w_village_basic", PRIYA, id="not-a-desk-world"),
    pytest.param("w_desk_", PRIYA, id="empty-desk-suffix"),
    pytest.param("w_desk_" + "a" * 60, PRIYA, id="too-long"),
    pytest.param("w_desk_priya\n", PRIYA, id="trailing-newline"),
    pytest.param("w_desk_sam", SAM, id="desk-world-of-someone-else"),
    pytest.param("w_desk_priya", None, id="owner-unknown"),
    pytest.param("w_desk_priya", OWNER, id="owner-not-the-record-owner"),
    pytest.param(None, PRIYA, id="not-a-string"),
    pytest.param(["w_desk_priya"], PRIYA, id="a-list"),
    pytest.param("w_desk_" + u(0x661, 0x662, 0x663), PRIYA, id="arabic-indic-digits"),
    pytest.param("w_desk_" + u(0xFF50, 0xFF52, 0xFF49, 0xFF59, 0xFF41), PRIYA, id="fullwidth-letters"),
    pytest.param("w_desk_pri" + u(0x443) + "a", PRIYA, id="cyrillic-u-lookalike"),
    pytest.param("w_desk_" + u(0x212A) + "1", PRIYA, id="kelvin-sign"),
]


@pytest.mark.parametrize(("answer", "owner"), HOSTILE)
def test_PPL_11c_s5_HR_1_a_desk_answer_that_is_not_the_owners_desk_world_fails_closed_on_create(
    people_rig, answer, owner
):
    rig = work_rig(people_rig)
    rig.desks = _Desks(answer, owner)
    before = rig.snapshot()
    response = rig.post("/v1/work-items", WORK_ITEM_BODY)
    assert response.status_code == 503 and response.json() == UNAVAILABLE, response.text[:200]
    assert rig.snapshot() == before and emitted(rig) == [] and _all_events(rig) == []
    assert "w_" not in response.text and "priya" not in response.text.lower()


@pytest.mark.parametrize(("answer", "owner"), HOSTILE)
@pytest.mark.parametrize("action", ["done", "edit", "snooze", "not-mine"])
def test_PPL_11c_s5_HR_1_a_desk_answer_that_is_not_the_owners_desk_world_undoes_a_change(
    people_rig, action, answer, owner
):
    rig = work_rig(people_rig)
    item_id = item_for(rig, action)
    rig.desks = _Desks(answer, owner)
    before = rig.stored("work_items", item_id)
    failed = act(rig, action, item_id)
    assert failed.status_code == 503 and failed.json() == UNAVAILABLE, failed.text[:200]
    assert rig.stored("work_items", item_id) == before, "the committed write was undone"
    assert emitted(rig) == [] and _all_events(rig) == []
    assert "w_" not in failed.text


# u_sam is the assignee of the confirm, so u_sam's world and owner are the right answer there, not hostile:
NOT_FOR_CONFIRM = {"owner-not-the-record-owner", "desk-world-of-someone-else"}


@pytest.mark.parametrize(("answer", "owner"), [p for p in HOSTILE if p.id not in NOT_FOR_CONFIRM])
def test_PPL_11c_s5_HR_1_a_hostile_desk_answer_undoes_a_confirm_and_never_lands_in_another_world(
    people_rig, answer, owner
):
    rig = meeting_rig(people_rig)
    before = rig.stored("work_items", "wi_launch_note")
    rig.desks = _Desks(answer, owner)
    response = rig.post("/v1/work-items/wi_launch_note/confirm")
    assert response.status_code == 503 and response.json() == UNAVAILABLE
    assert rig.stored("work_items", "wi_launch_note") == before and before["status"] == "proposed"
    assert emitted(rig) == [] and _all_events(rig) == []


def test_PPL_11c_s5_PE_12_a_confirm_whose_seam_answers_the_confirmers_world_is_refused(people_rig):
    """The confirm belongs to the assignee's Desk world: u_owner's own Desk world is a Desk world and u_owner's,
    but it is not the world of the person who may read the record, so nothing is written there."""
    rig = meeting_rig(people_rig)
    rig.desks = _Desks("w_desk_owner", OWNER)
    response = rig.post("/v1/work-items/wi_launch_note/confirm")
    assert response.status_code == 503 and response.json() == UNAVAILABLE
    assert rig.stored("work_items", "wi_launch_note")["status"] == "proposed" and _all_events(rig) == []


def test_PPL_11c_s5_PE_12_a_seam_answering_the_right_id_and_owner_still_works_in_that_world(people_rig):
    rig = work_rig(people_rig)
    rig.desks = _Desks("w_desk_" + "ab12" * 6, PRIYA)  # another id scheme (hex digest) with the right owner
    response = rig.post("/v1/work-items", WORK_ITEM_BODY)
    assert response.status_code == 201, response.text[:200]
    [(world, part)] = emitted(rig)
    assert world == "w_desk_" + "ab12" * 6 and part["type"] == "work_item.created" and part["actor"] == PRIYA
    assert [e["id"] for e in stamped(rig, world)] == [part["id"]]


def test_PPL_11c_s5_PE_12_a_confirm_still_goes_to_the_assignees_world_with_the_confirmer_as_actor(people_rig):
    rig = meeting_rig(people_rig)
    assert rig.post("/v1/work-items/wi_launch_note/confirm").status_code == 200
    [(world, part)] = emitted(rig)
    assert world == "w_desk_sam" and part["actor"] == OWNER and part["target"] == SAM
    assert len(stamped(rig, "w_desk_sam")) == 1 and _all_events(rig) == stamped(rig, "w_desk_sam")


def _dev_desks(monkeypatch):
    from tilo_api import deps, dev  # noqa: PLC0415

    for name in ("LIVE", "K_SERVICE", "CLOUD_RUN_JOB"):
        monkeypatch.delenv(name, raising=False)
    store = deps.Store()
    return store, dev.DevDeskWorlds(store)


def test_PPL_11c_s5_HR_1_dev_desk_worlds_refuse_a_desk_id_held_by_another_persons_world(monkeypatch):
    from tilo_api import deps  # noqa: PLC0415

    store, desks = _dev_desks(monkeypatch)
    store.worlds["w_desk_priya"] = deps.WorldRecord(owner=SAM, districts={})
    with pytest.raises(ValueError):  # noqa: PT011 (the same refusal as a user id that cannot make a world id)
        desks.desk_world("org_tilo", PRIYA)
    held = store.worlds["w_desk_priya"]
    assert held.owner == SAM and held.districts == {}, "never adopted, never overwritten"


def test_PPL_11c_s5_PE_12_dev_desk_worlds_stay_idempotent_for_their_own_person_and_name_the_owner(monkeypatch):
    store, desks = _dev_desks(monkeypatch)
    assert desks.desk_world("org_tilo", PRIYA) == desks.desk_world("org_tilo", PRIYA) == "w_desk_priya"
    assert desks.desk_owner("w_desk_priya") == PRIYA and store.worlds["w_desk_priya"].owner == PRIYA
    assert desks.desk_owner("w_desk_sam") is None and desks.desk_owner("w_village_basic") is None


class _LyingStr(str):
    """Its value is a well-formed Desk id (so a pattern match and an owner lookup accept it) but it prints as a
    world that is not a Desk world."""

    def __str__(self) -> str:
        return "w_village_basic"


def test_PPL_11c_s5_HR_1_a_str_subclass_that_lies_about_itself_is_refused(people_rig):
    rig = work_rig(people_rig)
    rig.desks = _Desks(_LyingStr("w_desk_priya"), PRIYA)
    before = rig.snapshot()
    response = rig.post("/v1/work-items", WORK_ITEM_BODY)
    assert response.status_code == 503 and response.json() == UNAVAILABLE, response.text[:200]
    assert rig.snapshot() == before and emitted(rig) == [] and _all_events(rig) == []
