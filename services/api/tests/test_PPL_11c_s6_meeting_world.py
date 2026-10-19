"""PPL-11c slice 6: writing `meeting.world_id` (BQ-273, ADR-0020, PE-22, FR-MTG-07; API_PPL_11c.md section 6).

`world_id` is the world that holds a meeting's transcript and minutes: written by tilo-api when it creates that world,
never taken from a request, and read by the quote and minutes routes to build the artifact scope. The route is
`POST /v1/meetings/{meeting_id}/world` (owner only, empty body): it asks `deps.get_meeting_worlds().make_meeting_world(
org_id=, owner=, meeting_id=)` for the world (the Outpost world, FR-MTG-07; idempotent per meeting), checks the answer
is a world id, and stores it once, by compare-and-set. A meeting that has one answers 200 unchanged and the maker is not
asked again.

Needs change in `packages/people` (not in `contracts/`): `check_write` has no row that adds `world_id` (`create`
refuses it, the `meeting` `edit` row does not list it, so the field would be `immutable`). The route is pinned over
HTTP only; a builder adds the one row (absent to a world id, owner only) with its own tests in that package.
"""

from __future__ import annotations

import pytest
from _ppl11a_lib import DEV, MEERA, OTHER_ORG, OWNER, PRIYA, SAM, conforms
from _ppl11c_lib import (
    MEETING_BODY,
    R_MT_WORLD,
    UNIQUE_ID,
    assert_gated,
    assert_unwired_is_503,
    gone_meeting,
    meeting_rig,
    path_of,
    refusals,
)

NEW_MT = UNIQUE_ID.replace("wi_", "mt_")


def _world(rig, meeting_id: str, body=None):
    rig.require_route(R_MT_WORLD)
    return rig.client.post(path_of(R_MT_WORLD, meeting_id=meeting_id), json={} if body is None else body)


def _new_meeting(people_rig, actor: str = PRIYA):
    rig = people_rig()
    rig.add_people()
    rig.as_user(actor)
    meeting_id = rig.post("/v1/meetings", MEETING_BODY).json()["id"]
    return rig, meeting_id


def test_PPL_11c_s6_BQ_273_the_owner_gets_the_meetings_world_written_once_and_never_from_the_request(people_rig):
    rig, meeting_id = _new_meeting(people_rig)
    before = rig.stored("meetings", meeting_id)
    assert "world_id" not in before
    version = rig.version_of("meetings", meeting_id)
    response = _world(rig, meeting_id)
    assert response.status_code == 200, response.text[:300]
    stored = rig.stored("meetings", meeting_id)
    assert response.json() == stored and conforms("meeting.schema.json", stored)
    assert stored["world_id"] == "w_meeting_" + meeting_id[3:], "exactly the id the world maker answered"
    assert {k: v for k, v in stored.items() if k != "world_id"} == before, "nothing else changed"
    assert rig.version_of("meetings", meeting_id) == version + 1
    assert rig.world_maker.calls == [(rig.org, PRIYA, meeting_id)]


def test_PPL_11c_s6_BQ_273_a_second_call_is_the_same_answer_and_the_maker_is_not_asked_again(people_rig):
    rig, meeting_id = _new_meeting(people_rig)
    first = _world(rig, meeting_id)
    snapshot = rig.snapshot()
    again = _world(rig, meeting_id)
    assert again.status_code == 200 and again.json() == first.json()
    assert rig.snapshot() == snapshot and len(rig.world_maker.calls) == 1
    seeded = meeting_rig(people_rig)  # `mt_q4_plan` already has `w_meeting_q4_plan`
    assert _world(seeded, "mt_q4_plan").status_code == 200 and seeded.world_maker.calls == []


@pytest.mark.parametrize(
    "body",
    [{"world_id": "w_someone_elses"}, {"world": "w_x"}, {"owner": SAM}, {"status": "live"}, [], "world"],
    ids=lambda b: str(b)[:30],
)
def test_PPL_11c_s6_PE_19_the_world_never_comes_from_the_body(people_rig, body):
    rig, meeting_id = _new_meeting(people_rig)
    before = rig.snapshot()
    assert _world(rig, meeting_id, body).status_code == 422
    assert rig.snapshot() == before and rig.world_maker.calls == []


def test_PPL_11c_s6_PE_05_only_the_owner_asks_for_the_world_and_a_gone_meeting_has_none(people_rig):
    rig, meeting_id = _new_meeting(people_rig)
    rig.real.meetings.create({**rig.stored("meetings", meeting_id), "id": "mt_elsewhere", "org_id": OTHER_ORG})
    before = rig.snapshot()
    seen = []
    for actor in (DEV, SAM, MEERA, OWNER, "u_ghost"):
        rig.as_user(actor)
        seen += [_world(rig, i) for i in (meeting_id, "mt_elsewhere", NEW_MT, "bad_id")]
    assert {r.status_code for r in seen} == {404} and len(refusals(seen)) == 1
    assert rig.snapshot() == before and rig.world_maker.calls == [], "a stranger makes no world"
    rig.as_user(PRIYA)
    meeting = rig.stored("meetings", meeting_id)
    for n, status in enumerate(("discarded", "deleted"), start=1):
        rig.real.meetings.replace(gone_meeting(meeting, status), expected_version=n)
        assert _world(rig, meeting_id).status_code == 404, status
    assert rig.world_maker.calls == []


@pytest.mark.parametrize(
    "answer", ["https://evil.example/w", "mt_q4_plan", "w_", "w_bad id", "w_" + "x" * 49, 7, ["w_x"], ""]
)
def test_PPL_11c_s6_PE_22_an_answer_that_is_not_a_world_id_is_never_stored(people_rig, answer):
    rig, meeting_id = _new_meeting(people_rig)
    rig.world_maker.answer = answer
    before = rig.snapshot()
    response = _world(rig, meeting_id)
    assert response.status_code == 503 and set(response.json()) == {"detail"}
    assert rig.snapshot() == before and "world_id" not in rig.stored("meetings", meeting_id)


def test_PPL_11c_s6_PE_19_a_maker_that_fails_is_a_503_and_a_lost_compare_and_set_is_a_409(people_rig):
    rig, meeting_id = _new_meeting(people_rig)
    before = rig.snapshot()
    rig.world_maker.fail = True
    assert _world(rig, meeting_id).status_code == 503 and rig.snapshot() == before
    rig.world_maker.fail = False
    rig.conflicting_stores("meetings")
    lost = _world(rig, meeting_id)
    assert lost.status_code == 409 and lost.json()["code"] == "version_conflict", lost.text[:200]
    assert [c for c in rig.store_calls if c[:2] == ("meeting", "replace")] == [("meeting", "replace", rig.org)]
    assert rig.snapshot() == before
    rig.stores.meetings.fail_replace = False
    assert _world(rig, meeting_id).status_code == 200, "the retry finds the same world"


def test_PPL_11c_s6_PE_22_with_a_world_the_owner_route_can_read_what_was_put_in_that_scope(people_rig):
    """The point of the field: a meeting whose world is set yields quotes (404 without it, ADR-0020 BQ-273)."""
    from _ppl11a_lib import fixture_case  # noqa: PLC0415

    case = fixture_case(
        "transcript", "invalid", "pe23_meeting_without_a_world"
    )  # artifacts stored in w_meeting_q4_plan
    rig = people_rig()
    rig.seed_quote_case(case)
    rig.as_user(OWNER)
    path = "/v1/meetings/mt_q4_plan/quotes"
    assert rig.get(path, params={"ids": "u0021"}).status_code == 404, "no world, no quote"
    rig.world_maker.answer = "w_meeting_q4_plan"
    assert _world(rig, "mt_q4_plan").status_code == 200
    quotes = rig.get(path, params={"ids": "u0021"})
    assert quotes.status_code == 200 and [q["state"] for q in quotes.json()["quotes"]] == ["shown"]


def test_PPL_11c_s6_SEC_15_the_world_route_is_gated_and_fails_closed(people_rig):
    assert_gated(people_rig, [R_MT_WORLD])
    assert_unwired_is_503(people_rig, [R_MT_WORLD], "people_stores")
    rig, meeting_id = _new_meeting(people_rig)
    rig.unwire("meeting_worlds")
    before = rig.snapshot()
    response = _world(rig, meeting_id)
    assert response.status_code == 503 and response.json() == {"detail": "not_configured"}
    assert rig.snapshot() == before
