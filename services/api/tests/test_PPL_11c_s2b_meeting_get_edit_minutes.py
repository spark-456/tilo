"""PPL-11c slice 2b: the meeting owner reads and edits the meeting and reads its minutes (PE-05 owner only, PE-07 and
BQ-PPL10-6 what an edit may change, PE-13 no link in a title, PE-19 stamps, PE-22/PE-24 minutes text; API_PPL_11c.md
section 3).

* `GET /v1/meetings/{id}`: the stored meeting, to its owner only (a deleted meeting is gone for everyone).
* `POST /v1/meetings/{id}/edit`: title, series, scheduled, agenda, attendees; nothing else, ever.
* `GET /v1/meetings/{id}/minutes`: the minutes document, read through the artifact store with the meeting's own scope.
"""

from __future__ import annotations

import copy

import pytest
from _ppl11a_lib import DEV, MEERA, NOW, OTHER_ORG, OWNER, PRIYA, SAM, conforms, fake_token, u
from _ppl11c_lib import (
    R_MT_EDIT,
    R_MT_GET,
    R_MT_MINUTES,
    UNIQUE_ID,
    assert_gated,
    assert_unwired_is_503,
    gone_meeting,
    meeting_rig,
    path_of,
    refusals,
    transcript_case,
)

NEW_MT = UNIQUE_ID.replace("wi_", "mt_")
ART_MINUTES = {"artifact_id": "art_minutes_q4_plan", "version": 1}


def _get(rig, meeting_id: str = "mt_q4_plan"):
    rig.require_route(R_MT_GET)
    return rig.get(path_of(R_MT_GET, meeting_id=meeting_id))


def _edit(rig, body, meeting_id: str = "mt_q4_plan"):
    rig.require_route(R_MT_EDIT)
    return rig.client.post(path_of(R_MT_EDIT, meeting_id=meeting_id), json=body)


def _minutes(rig, meeting_id: str = "mt_q4_plan"):
    rig.require_route(R_MT_MINUTES)
    return rig.get(path_of(R_MT_MINUTES, meeting_id=meeting_id))


# --- get ------------------------------------------------------------------------------------------------------------


def test_PPL_11c_s2b_PE_05_the_owner_reads_the_meeting_in_full_and_nobody_else_reads_anything(people_rig):
    rig = meeting_rig(people_rig)
    stored = rig.stored("meetings", "mt_q4_plan")
    mine = _get(rig)
    assert mine.status_code == 200 and mine.json() == stored and conforms("meeting.schema.json", mine.json())
    seen = []
    for actor in (PRIYA, DEV, SAM, MEERA, "u_ghost"):  # an attendee, a teammate, an org owner, a stranger
        rig.as_user(actor)
        seen += [_get(rig, i) for i in ("mt_q4_plan", NEW_MT, "bad_id")]
    assert {r.status_code for r in seen} == {404} and len(refusals(seen)) == 1, "one body whatever the cause"


def test_PPL_11c_s2b_FR_MTG_10_a_discarded_meeting_is_still_the_owners_to_read_and_a_deleted_one_is_gone(people_rig):
    rig = meeting_rig(people_rig)
    meeting = rig.stored("meetings", "mt_q4_plan")
    rig.real.meetings.replace(gone_meeting(meeting, "discarded"), expected_version=1)
    assert _get(rig).status_code == 200 and _get(rig).json()["status"] == "discarded"
    rig.real.meetings.replace(gone_meeting(meeting, "deleted"), expected_version=2)
    deleted = _get(rig)
    assert deleted.status_code == 404, "the owner asked for it to go: nothing of it is read back"
    assert "Q4 planning" not in deleted.text


# --- edit -----------------------------------------------------------------------------------------------------------


def test_PPL_11c_s2b_PE_07_the_owner_edits_title_series_schedule_agenda_and_attendees(people_rig):
    """Given the owner's minuted meeting, when they edit all five editable fields, then 200 with the stored meeting;
    those five are the new values, every other field is as stored (status, minutes, `minutes_confirmed_by`, world,
    attestation, artifact references, deletion dates), and the version moves by one. An attendee's `user` is kept
    for a name that stays and is null for a name that is new: it is never taken from a request (PE-15)."""
    rig = meeting_rig(people_rig)
    before = rig.stored("meetings", "mt_q4_plan")
    version = rig.version_of("meetings", "mt_q4_plan")
    body = {
        "title": "Q4 planning (moved)",
        "series": "q4_planning_monthly",
        "scheduled": {"start": "2026-10-08T09:00:00.000Z", "end": "2026-10-08T10:00:00.000Z"},
        "agenda": [{"title": "Rate sheet", "minutes": 20}, {"title": "Launch note", "minutes": None}],
        "attendees": [{"name": "Priya"}, {"name": "Asha Rao"}, {"name": "Newcomer"}],
    }
    response = _edit(rig, body)
    assert response.status_code == 200, response.text[:300]
    stored = rig.stored("meetings", "mt_q4_plan")
    assert response.json() == stored and conforms("meeting.schema.json", stored)
    assert {k: stored[k] for k in body if k != "attendees"} == {k: v for k, v in body.items() if k != "attendees"}
    assert stored["attendees"] == [
        {"name": "Priya", "user": PRIYA},
        {"name": "Asha Rao", "user": OWNER},
        {"name": "Newcomer", "user": None},
    ]
    untouched = ("id", "org_id", "owner", "world_id", "attestation", "source", "status", "ended_reason",
                 "minutes_confirmed_by", "transcript", "minutes", "delete_transcript_after", "delete_minutes_after",
                 "created_at")  # fmt: skip
    assert all(stored[k] == before[k] for k in untouched)
    assert rig.version_of("meetings", "mt_q4_plan") == version + 1


def test_PPL_11c_s2b_PE_07_an_edit_may_name_one_field_and_null_the_optional_ones(people_rig):
    rig = meeting_rig(people_rig)
    assert _edit(rig, {"title": "Renamed"}).json()["agenda"] == rig.stored("meetings", "mt_q4_plan")["agenda"]
    cleared = _edit(rig, {"series": None, "scheduled": None, "agenda": [], "attendees": []})
    assert cleared.status_code == 200
    stored = rig.stored("meetings", "mt_q4_plan")
    assert (stored["series"], stored["scheduled"], stored["agenda"], stored["attendees"]) == (None, None, [], [])


MEETING_FORBIDDEN = [
    {"source": "bot"},
    {"status": "deleted"},
    {"status": "minuted"},
    {"owner": SAM},
    {"world_id": "w_someone_elses"},
    {"attestation": {"by": OWNER, "at": NOW, "notice_version": "9.9.9"}},
    {"minutes_confirmed_by": {"by": OWNER, "at": NOW}},
    {"minutes_confirmed_by": None},
    {"transcript": {"artifact_id": "art_other", "version": 1}},
    {"minutes": {"artifact_id": "art_other", "version": 1}},
    {"delete_transcript_after": "2099-01-01T00:00:00.000Z"},
    {"delete_minutes_after": "2099-01-01T00:00:00.000Z"},
    {"ended_reason": "completed"},
    {"id": "mt_other"},
    {"org_id": "org_elsewhere"},
    {"created_at": "2020-01-01T00:00:00.000Z"},
    {"attendees": [{"name": "Priya", "user": SAM}]},
    {"agenda": [{"title": "x", "minutes": 5, "evidence": []}]},
    {"scheduled": {"start": NOW, "end": None, "link": "x"}},
    {},
    [],
    "edit",
]


@pytest.mark.parametrize("body", MEETING_FORBIDDEN, ids=lambda b: str(b)[:40])
def test_PPL_11c_s2b_PE_19_an_edit_names_only_its_five_fields_and_never_a_stamp_a_source_or_a_world(people_rig, body):
    rig = meeting_rig(people_rig)
    before = rig.snapshot()
    response = _edit(rig, body)
    assert response.status_code == 422, (body, response.status_code, response.text[:200])
    assert rig.snapshot() == before


def test_PPL_11c_s2b_PE_13_a_link_a_secret_and_hidden_characters_are_handled_like_on_create(people_rig):
    secret, hidden = fake_token(), u(0x202E, 0x200B, 0x2028)
    rig = meeting_rig(people_rig)
    ok = _edit(rig, {"title": f"Pl{hidden}an Q4", "agenda": [{"title": f"Rate{hidden} sheet", "minutes": 5}]})
    assert ok.status_code == 200 and ok.json()["title"] == "Plan Q4" and ok.json()["agenda"][0]["title"] == "Rate sheet"
    assert all(h not in call for call in rig.redactor.calls for h in hidden)
    before = rig.snapshot()
    for body in (
        {"title": "https://evil.example/x"},
        {"title": f"https:{u(0x200B)}//evil.example"},
        {"title": "meet.google.com"},
        {"agenda": [{"title": "see http://evil.example", "minutes": 1}]},
        {"attendees": [{"name": "x https://e.example"}]},
        {"title": "x" * 121},
        {"title": f"a{chr(10)}b"},
        {"series": "Not A Series"},
    ):
        assert _edit(rig, body).status_code == 422, body
    assert rig.snapshot() == before
    redacted = _edit(rig, {"title": f"Plan {secret}"})
    assert redacted.status_code == 200 and secret not in redacted.text and "[REDACTED]" in redacted.json()["title"]


def test_PPL_11c_s2b_PE_05_only_the_owner_edits_and_a_gone_meeting_is_not_editable(people_rig):
    rig = meeting_rig(people_rig)
    rig.real.meetings.create({**rig.stored("meetings", "mt_q4_plan"), "id": "mt_elsewhere", "org_id": OTHER_ORG})
    before = rig.snapshot()
    seen = []
    for actor in (PRIYA, DEV, SAM, MEERA, "u_ghost"):
        rig.as_user(actor)
        seen += [_edit(rig, {"title": "Hijacked"}, i) for i in ("mt_q4_plan", "mt_elsewhere", NEW_MT, "bad_id")]
    assert {r.status_code for r in seen} == {404} and len(refusals(seen)) == 1
    assert rig.snapshot() == before
    rig.as_user(OWNER)
    meeting = rig.stored("meetings", "mt_q4_plan")
    for n, status in enumerate(("discarded", "deleted"), start=1):
        rig.real.meetings.replace(gone_meeting(meeting, status), expected_version=n)
        assert _edit(rig, {"title": "Too late"}).status_code == 404, status


def test_PPL_11c_s2b_PE_19_a_lost_compare_and_set_is_a_409_after_one_attempt_and_no_directory_is_listed(people_rig):
    rig = meeting_rig(people_rig)
    before = rig.snapshot()
    rig.conflicting_stores("meetings")
    del rig.store_calls[:]
    lost = _edit(rig, {"title": "Renamed"})
    assert lost.status_code == 409 and lost.json()["code"] == "version_conflict", lost.text[:200]
    assert [c for c in rig.store_calls if c[:2] == ("meeting", "replace")] == [("meeting", "replace", rig.org)]
    assert ("person", "list", rig.org) not in rig.store_calls
    assert rig.snapshot() == before


def test_PPL_11c_s2b_SEC_15_the_meeting_read_and_edit_routes_are_gated_and_fail_closed(people_rig):
    routes = [R_MT_GET, R_MT_EDIT, R_MT_MINUTES]
    assert_gated(people_rig, routes)
    assert_unwired_is_503(people_rig, routes, "people_stores")


# --- minutes --------------------------------------------------------------------------------------------------------


def test_PPL_11c_s2b_PE_05_the_owner_reads_the_minutes_document_and_it_is_never_cached(people_rig):
    case = transcript_case("owner_reads_quotes")
    rig = meeting_rig(people_rig)
    before = rig.snapshot()
    response = _minutes(rig)
    assert response.status_code == 200, response.text[:300]
    assert conforms("minutes.schema.json", response.json())
    assert response.json() == case["minutes"], "the stored document, nothing added and nothing cut"
    assert response.headers["cache-control"] == "no-store"
    assert "utterances" not in response.text, "no transcript line is part of the minutes"
    assert rig.snapshot() == before, "a read changes no record and no artifact"


def test_PPL_11c_s2b_PE_05_the_minutes_can_be_read_before_the_owner_confirms_them(people_rig):
    rig = meeting_rig(people_rig, "owner_reads_quotes")
    meeting = rig.stored("meetings", "mt_q4_plan")
    rig.real.meetings.replace({**meeting, "minutes_confirmed_by": None}, expected_version=1)
    assert _minutes(rig).status_code == 200, "S-26 shows the owner the minutes in order to confirm them"


def test_PPL_11c_s2b_PE_05_everyone_but_the_owner_gets_the_one_404_and_so_does_a_meeting_with_no_readable_minutes(
    people_rig,
):
    rig = meeting_rig(people_rig)
    meeting = rig.stored("meetings", "mt_q4_plan")
    rig.add("meetings", _without(meeting, "world_id", "mt_no_world"))
    rig.add("meetings", {**meeting, "id": "mt_ended", "status": "ended", "minutes": None, "minutes_confirmed_by": None})
    rig.real.meetings.create({**meeting, "id": "mt_elsewhere", "org_id": OTHER_ORG})
    seen = []
    for actor in (PRIYA, DEV, SAM, MEERA, "u_ghost"):  # an assignee, a teammate, an org owner and a stranger
        rig.as_user(actor)
        seen += [_minutes(rig, "mt_q4_plan")]
    rig.as_user(OWNER)
    for meeting_id in ("mt_no_world", "mt_ended", "mt_elsewhere", NEW_MT, "bad_id"):
        seen.append(_minutes(rig, meeting_id))
    assert {r.status_code for r in seen} == {404} and len(refusals(seen)) == 1


def _without(meeting: dict, key: str, new_id: str) -> dict:
    out = copy.deepcopy(meeting)
    out.pop(key)
    out["id"] = new_id
    return out


@pytest.mark.parametrize("status", ["discarded", "deleted"])
def test_PPL_11c_s2b_FR_MTG_10_the_minutes_of_a_discarded_or_deleted_meeting_are_gone(people_rig, status):
    rig = meeting_rig(people_rig)
    rig.real.meetings.replace(gone_meeting(rig.stored("meetings", "mt_q4_plan"), status), expected_version=1)
    assert _minutes(rig).status_code == 404


def test_PPL_11c_s2b_FR_MTG_10_minutes_end_at_delete_minutes_after_compared_with_the_server_clock(people_rig):
    """`delete_minutes_after` is 2027-01-03T10:00:00.000Z: one millisecond before it the owner still reads them; at it,
    404 (the same `>=` the transcript sweep uses)."""
    rig = meeting_rig(people_rig)
    rig.set_now("2027-01-03T09:59:59.999Z")
    assert _minutes(rig).status_code == 200
    rig.set_now("2027-01-03T10:00:00.000Z")
    assert _minutes(rig).status_code == 404


def test_PPL_11c_s2b_PE_22_minutes_that_are_missing_corrupt_or_another_meetings_are_never_shown(people_rig):
    from tilo_memory.artifacts import Scope  # noqa: PLC0415

    rig = meeting_rig(people_rig)
    meeting = rig.stored("meetings", "mt_q4_plan")
    scope = Scope(meeting["org_id"], meeting["world_id"], meeting["owner"])
    rig.add("meetings", {**meeting, "id": "mt_missing", "minutes": {"artifact_id": "art_not_there", "version": 1}})
    rig.put_doc(scope, "art_minutes_corrupt", ["not", "a", "document"])
    rig.add(
        "meetings", {**meeting, "id": "mt_corrupt", "minutes": {"artifact_id": "art_minutes_corrupt", "version": 1}}
    )
    other = {**transcript_case()["minutes"], "meeting_id": "mt_somebody_else"}
    rig.put_doc(scope, "art_minutes_other", other)
    rig.add("meetings", {**meeting, "id": "mt_swapped", "minutes": {"artifact_id": "art_minutes_other", "version": 1}})
    assert _minutes(rig, "mt_missing").status_code == 404, "no such version in the meeting's own scope"
    assert _minutes(rig, "mt_swapped").status_code == 404, "minutes that name another meeting are not this meeting's"
    corrupt = _minutes(rig, "mt_corrupt")
    assert corrupt.status_code == 503 and set(corrupt.json()) == {"detail"}, "never a partial answer"


def test_PPL_11c_s2b_PE_24_the_minutes_text_is_cleaned_and_redacted_like_every_other_text(people_rig):
    """Owner or not, a secret never leaves in a response: the redactor runs on every text of the minutes and the format
    and separator characters are removed first. The document stays schema-valid."""
    from tilo_memory.artifacts import Scope  # noqa: PLC0415

    secret, hidden = fake_token(), u(0x202E, 0x200B)
    rig = meeting_rig(people_rig)
    meeting = rig.stored("meetings", "mt_q4_plan")
    doc = copy.deepcopy(transcript_case()["minutes"])
    doc["summary"][0]["text"] = f"Send the rate{hidden} sheet {secret}"
    doc["decisions"][0]["text"] = f"Use the new{hidden} column"
    rig.put_doc(Scope(meeting["org_id"], meeting["world_id"], meeting["owner"]), "art_minutes_dirty", doc)
    rig.add("meetings", {**meeting, "id": "mt_dirty", "minutes": {"artifact_id": "art_minutes_dirty", "version": 1}})
    response = _minutes(rig, "mt_dirty")
    assert response.status_code == 200, response.text[:300]
    assert secret not in response.text and all(h not in response.text for h in hidden)
    body = response.json()
    assert (
        body["summary"][0]["text"] == "Send the rate sheet [REDACTED]"
        and body["decisions"][0]["text"] == "Use the new column"
    )
    assert conforms("minutes.schema.json", body) and any(secret in call for call in rig.redactor.calls)


def test_PPL_11c_s2b_PE_19_the_minutes_read_needs_the_artifact_store_and_the_redactor_and_says_so_to_everyone(
    people_rig,
):
    for gone in ("artifact_store", "redactor"):
        rig = meeting_rig(people_rig)
        rig.unwire(gone)
        statuses = set()
        for actor in (OWNER, PRIYA, "u_ghost"):
            rig.as_user(actor)
            statuses.add((_minutes(rig).status_code, _minutes(rig, NEW_MT).status_code))
        assert statuses == {(503, 503)}, (gone, statuses)
