"""PPL-11c slice 2a: deleting a meeting deletes what was made from it, and nothing can be released from a meeting that
is gone (FR-MTG-10 "the Owner can delete a meeting and all derived data", PE-16, PE-19, PE-22, PE-23; PPL-11a
follow-ups #464 and #456; API_PPL_11c.md section 3).

* `POST /v1/meetings/{meeting_id}/delete` (owner only): removes the transcript and minutes artifacts, the *proposed*
  work items, pins and calendar entries made from the meeting, then leaves the PE-19 tombstone (compare-and-set last).
  What the owner already released (a confirmed item) stays the assignee's own, readable, its quote `expired`.
* `POST /v1/work-items/{id}/confirm` refuses (the one 404) a proposed item whose meeting is discarded or deleted.
* The item quote route answers `expired` on its gone path only when the item's assigner is the owner on the meeting
  record or tombstone (404 otherwise).
"""

from __future__ import annotations

import pytest
from _ppl11a_lib import DEV, MEERA, OTHER_ORG, OWNER, PRIYA, SAM, own_item
from _ppl11c_lib import (
    MEETING_BODY,
    R_MT_DELETE,
    UNIQUE_ID,
    as_proposed,
    assert_gated,
    assert_unwired_is_503,
    confirmed_item,
    gone_meeting,
    holds_artifact,
    meeting_rig,
    path_of,
    proposed_calendar_from_meeting,
    proposed_launch_note,
    proposed_pin_from_meeting,
    refusals,
    transcript_case,
)

TRANSCRIPT, MINUTES = "art_transcript_q4_plan", "art_minutes_q4_plan"


def _delete(rig, meeting_id: str = "mt_q4_plan"):
    rig.require_route(R_MT_DELETE)
    return rig.post(path_of(R_MT_DELETE, meeting_id=meeting_id))


def _with_derived(rig) -> None:
    """Proposed pin and calendar entry made from the meeting (dropped by a delete), and records that are not derived
    from it (kept): another meeting's proposed pin, an item the owner released, the owner's own item."""
    rig.add("pins", proposed_pin_from_meeting())
    rig.add("calendar", proposed_calendar_from_meeting())
    rig.add(
        "pins",
        {
            **proposed_pin_from_meeting(),
            "id": "pb_other_meeting",
            "source": {"kind": "meeting", "ref": "mt_other#ai1", "evidence": []},
        },
    )
    rig.add(
        "work_items",
        {
            **as_proposed(confirmed_item()),
            "id": "wi_other_meeting",
            "source": {"kind": "meeting", "ref": "mt_other#ai1", "evidence": ["u0001"]},
        },
    )
    rig.add("work_items", own_item("wi_owners_own", OWNER))


def test_PPL_11c_s2a_FR_MTG_10_deleting_a_meeting_removes_its_artifacts_and_its_proposed_derived_records(people_rig):
    """Given u_owner's minuted meeting with its transcript and minutes, a proposed item for u_sam, a proposed pin and a
    proposed calendar entry made from it, when the owner deletes it, then 200 `{id, status: deleted}`; the stored
    meeting is exactly its PE-19 tombstone (version + 1); neither artifact is in the store (records or blobs); the
    proposed item, pin and calendar entry are gone; what is not derived from it, and what the owner released, stays."""
    from tilo_people.stores import meeting_tombstone  # noqa: PLC0415

    rig = meeting_rig(people_rig)
    _with_derived(rig)
    before = rig.stored("meetings", "mt_q4_plan")
    version = rig.version_of("meetings", "mt_q4_plan")
    assert holds_artifact(rig, TRANSCRIPT) and holds_artifact(rig, MINUTES)
    response = _delete(rig)
    assert response.status_code == 200, response.text[:300]
    assert response.json() == {"id": "mt_q4_plan", "status": "deleted"}
    assert rig.stored("meetings", "mt_q4_plan") == meeting_tombstone(before)
    assert rig.version_of("meetings", "mt_q4_plan") == version + 1
    assert not holds_artifact(rig, TRANSCRIPT) and not holds_artifact(rig, MINUTES), (
        "the transcript or minutes survived"
    )
    assert rig.stored("work_items", "wi_launch_note") is None, "a proposed item outlived its meeting (FR-MTG-10)"
    assert rig.stored("pins", "pb_from_meeting") is None and rig.stored("calendar", "ce_from_meeting") is None
    for kept_store, kept_id in (
        ("work_items", "wi_rate_sheet"),
        ("work_items", "wi_owners_own"),
        ("work_items", "wi_other_meeting"),
        ("pins", "pb_other_meeting"),
    ):
        assert rig.stored(kept_store, kept_id) is not None, f"{kept_id} is not derived from this meeting"


def test_PPL_11c_s2a_PE_23_an_item_the_owner_released_stays_readable_and_its_quote_is_expired(people_rig):
    rig = meeting_rig(people_rig)
    assert _delete(rig).status_code == 200
    rig.as_user(PRIYA)
    plate = rig.plate().json()
    assert [r["ref"]["id"] for r in plate["rows"]] == ["wi_rate_sheet"], "her confirmed item is still on her plate"
    quote = rig.get("/v1/work-items/wi_rate_sheet/quote")
    assert quote.status_code == 200
    assert [(q["utterance_id"], q["state"], q["transcript"], q["text"]) for q in quote.json()["quotes"]] == [
        ("u0021", "expired", None, None)
    ]
    rig.as_user(OWNER)
    owner_quote = rig.get("/v1/meetings/mt_q4_plan/quotes", params={"ids": "u0021,u0023"})
    assert owner_quote.status_code == 200 and {q["state"] for q in owner_quote.json()["quotes"]} == {"expired"}


def test_PPL_11c_s2a_PE_05_only_the_meeting_owner_deletes_and_everyone_else_gets_the_one_404(people_rig):
    """The assignee, a teammate, an org owner, a person with no record, an unknown id, a malformed id and another org's
    meeting: the same 404 body, and the meeting, its artifacts and everything made from it are untouched."""
    rig = meeting_rig(people_rig)
    _with_derived(rig)
    rig.real.meetings.create({**rig.stored("meetings", "mt_q4_plan"), "id": "mt_elsewhere", "org_id": OTHER_ORG})
    before = rig.snapshot()
    seen = []
    for actor in (PRIYA, DEV, SAM, MEERA, "u_ghost"):
        rig.as_user(actor)
        seen += [_delete(rig, i) for i in ("mt_q4_plan", "mt_elsewhere", UNIQUE_ID.replace("wi_", "mt_"), "bad_id")]
    assert {r.status_code for r in seen} == {404} and len(refusals(seen)) == 1
    assert rig.snapshot() == before and holds_artifact(rig, TRANSCRIPT) and holds_artifact(rig, MINUTES)


def test_PPL_11c_s2a_FR_MTG_10_a_second_delete_by_the_owner_is_the_same_answer_and_changes_nothing(people_rig):
    """A retry is safe (the first answer may have been lost): 200 again, no new version, nothing else touched."""
    rig = meeting_rig(people_rig)
    first = _delete(rig)
    snapshot = rig.snapshot()
    again = _delete(rig)
    assert first.status_code == again.status_code == 200 and again.json() == first.json()
    assert rig.snapshot() == snapshot
    rig.as_user(PRIYA)
    assert _delete(rig).status_code == 404, "a tombstone's delete is still the owner's alone"


def test_PPL_11c_s2a_FR_MTG_10_a_discarded_meeting_and_an_unstarted_one_can_be_deleted_too(people_rig):
    rig = people_rig()
    rig.add_people()
    meeting = transcript_case()["meeting"]
    rig.add("meetings", gone_meeting(meeting, "discarded"))
    rig.add("work_items", proposed_launch_note())
    rig.as_user(OWNER)
    assert _delete(rig).status_code == 200
    assert rig.stored("meetings", "mt_q4_plan")["status"] == "deleted"
    assert rig.stored("work_items", "wi_launch_note") is None
    rig.as_user(PRIYA)  # a meeting that never started: created over the API, then deleted by its owner
    made = rig.post("/v1/meetings", MEETING_BODY).json()["id"]
    assert _delete(rig, made).status_code == 200 and rig.stored("meetings", made)["status"] == "deleted"


def test_PPL_11c_s2a_FR_MTG_10_a_store_that_fails_leaves_the_meeting_live_and_a_retry_finishes_the_delete(
    people_rig, monkeypatch
):
    """Derived data goes first and the tombstone last, so a failure half way is a meeting that is still live and a
    retry that completes: 503 (no record text), the meeting still `minuted` with its artifact references, the proposed
    item still there; then the same call succeeds."""
    rig = meeting_rig(people_rig)
    _with_derived(rig)
    before = rig.snapshot()
    original = rig.blobs.delete

    def down(*args, **kwargs):
        raise OSError("the blob store is down")

    monkeypatch.setattr(rig.blobs, "delete", down)
    failed = _delete(rig)
    assert failed.status_code == 503 and "Q4 planning" not in failed.text and "u0021" not in failed.text
    assert rig.snapshot() == before and rig.stored("meetings", "mt_q4_plan")["status"] == "minuted"
    monkeypatch.setattr(rig.blobs, "delete", original)
    retried = _delete(rig)
    assert retried.status_code == 200
    assert not holds_artifact(rig, TRANSCRIPT) and rig.stored("work_items", "wi_launch_note") is None
    assert rig.stored("meetings", "mt_q4_plan")["status"] == "deleted"


def test_PPL_11c_s2a_PE_19_a_lost_compare_and_set_is_a_409_and_the_retry_completes_the_delete(people_rig):
    rig = meeting_rig(people_rig)
    rig.conflicting_stores("meetings")
    lost = _delete(rig)
    assert lost.status_code == 409 and lost.json()["code"] == "version_conflict", lost.text[:200]
    assert [c for c in rig.store_calls if c[:2] == ("meeting", "replace")] == [("meeting", "replace", rig.org)]
    rig.stores.meetings.fail_replace = False
    assert _delete(rig).status_code == 200
    assert rig.stored("meetings", "mt_q4_plan")["status"] == "deleted" and not holds_artifact(rig, MINUTES)


def test_PPL_11c_s2a_PE_19_a_delete_that_cannot_reach_the_artifact_store_is_503_for_everyone_and_changes_nothing(
    people_rig,
):
    rig = meeting_rig(people_rig)
    rig.unwire("artifact_store")
    before = rig.snapshot()
    statuses = set()
    for actor in (OWNER, PRIYA, SAM, "u_ghost"):
        rig.as_user(actor)
        response = _delete(rig)
        statuses.add((response.status_code, response.text))
    assert statuses == {(503, '{"detail":"not_configured"}')}, "no oracle: the owner and a stranger see the same"
    assert rig.snapshot() == before


def test_PPL_11c_s2a_SEC_15_the_delete_route_is_gated_and_fails_closed(people_rig):
    assert_gated(people_rig, [R_MT_DELETE])
    assert_unwired_is_503(people_rig, [R_MT_DELETE], "people_stores")


@pytest.mark.parametrize("body", [{"status": "deleted"}, {"keep_items": True}, {"owner": OWNER}, [], "delete"])
def test_PPL_11c_s2a_PE_19_a_delete_takes_an_empty_body_and_nothing_else(people_rig, body):
    rig = meeting_rig(people_rig)
    rig.require_route(R_MT_DELETE)
    before = rig.snapshot()
    assert rig.client.post("/v1/meetings/mt_q4_plan/delete", json=body).status_code == 422
    assert rig.snapshot() == before


# --- #464: nothing is released from a meeting that is gone ----------------------------------------------------------


@pytest.mark.parametrize("status", ["discarded", "deleted"])
def test_PPL_11c_s2a_FR_MTG_10_a_proposed_item_of_a_discarded_or_deleted_meeting_cannot_be_confirmed(
    people_rig, status
):
    """Confirming would release text taken from minutes the owner deleted (#464): the assigner gets the one 404 and
    the item stays as it was, even if the proposed item itself was never swept."""
    rig = people_rig()
    rig.add_people()
    rig.add("meetings", gone_meeting(transcript_case()["meeting"], status))
    rig.add("work_items", as_proposed(confirmed_item()))
    rig.as_user(OWNER)
    before = rig.snapshot()
    rig.require_route(("POST", "/v1/work-items/{work_item_id}/confirm"))
    refused = rig.post("/v1/work-items/wi_rate_sheet/confirm")
    unknown = rig.post(f"/v1/work-items/{UNIQUE_ID}/confirm")
    assert refused.status_code == 404 and refused.text == unknown.text, refused.text[:200]
    assert rig.snapshot() == before


# --- #456: the item quote's gone path needs the owner to match ------------------------------------------------------


def _forged_assigner_item() -> dict:
    """A Tilo-made, confirmed item for u_priya whose assigner and confirmer is u_sam, not the meeting's owner."""
    item = confirmed_item()
    item["assigned_by"] = {"by": SAM, "at": item["assigned_by"]["at"]}
    item["confirmed_by"] = {"by": SAM, "at": item["confirmed_by"]["at"]}
    item["history"][1]["by"] = SAM
    return item


@pytest.mark.parametrize("status", ["discarded", "deleted"])
def test_PPL_11c_s2a_PE_19_an_expired_quote_needs_the_assigner_to_be_the_owner_on_the_record_or_tombstone(
    people_rig, status
):
    rig = people_rig()
    rig.add_people()
    meeting = transcript_case()["meeting"]
    rig.add("meetings", gone_meeting(meeting, status))
    rig.add("work_items", _forged_assigner_item())
    rig.as_user(PRIYA)
    unknown = rig.get(f"/v1/work-items/{UNIQUE_ID}/quote")
    forged = rig.get("/v1/work-items/wi_rate_sheet/quote")
    assert forged.status_code == 404 and forged.text == unknown.text, "an assigner who is not the owner opens nothing"
    genuine = people_rig()
    genuine.add_people()
    genuine.add("meetings", gone_meeting(meeting, status))
    genuine.add("work_items", confirmed_item())
    genuine.as_user(PRIYA)
    ok = genuine.get("/v1/work-items/wi_rate_sheet/quote")
    assert ok.status_code == 200 and [q["state"] for q in ok.json()["quotes"]] == ["expired"]
