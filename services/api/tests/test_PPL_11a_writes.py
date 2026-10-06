"""PPL-11a slice C: the writes around the read models (API_PPL_11a.md section 5): confirm (a meeting's minutes, a
proposed work item), create a meeting (the attestation is stamped by the server), create a person (the id is minted by
the server), create a person-made work item (mail and request sources must be the caller's own). Every write runs
`tilo_people.decide`, builds `after` with stamps from the signed-in person and the server clock only, runs the secret
redactor BEFORE `check_write` (a secret that would push a title over its schema cap is redacted first, so it passes),
checks the schema and the MAY row, and stores with compare-and-set. A refusal on a record that exists is a 404 with
one body for every cause; a refused create is a 403. Bodies are JSON only (415) and closed (422 on any extra field):
no stamp, owner, id, org, status, source or history ever comes from a request, and `source.ref` never changes.
"""

from __future__ import annotations

import copy
import logging
import re
import time

import pytest
from _ppl11a_lib import (
    DEV,
    EARLY,
    MEERA,
    NOW,
    OWNER,
    PRIYA,
    SAM,
    conforms,
    fake_token,
    fixture_case,
    own_item,
    pl,
    released_item_case,
    run_threads,
)
from fastapi.testclient import TestClient

ID_RE = {"u": r"u_[0-9A-Za-z_]{1,48}", "mt": r"mt_[0-9A-Za-z_]{1,48}", "wi": r"wi_[0-9A-Za-z_]{1,48}"}
PERSON = {
    "display_name": "Nina Patel",
    "aliases": ["Nina"],
    "email": "nina.patel@example.com",
    "time_zone": "Asia/Kolkata",
    "preferred_channel": "web",
}
MEETING = {"title": "Weekly sync", "source": "upload"}


def _proposed_item(rig):
    """u_owner's Tilo-made, still-proposed item for u_priya from u_owner's meeting mt_q4_plan (ai1)."""
    case = released_item_case()
    rig.add_people()
    rig.add("meetings", case["source"]["meeting"])
    item = copy.deepcopy(case["source"]["data"])
    item.update(status="proposed", confirmed_by=None, updated_at=item["created_at"], history=item["history"][:1])
    rig.add("work_items", item)
    return item


def _unchanged(rig, before) -> None:
    assert rig.snapshot() == before, "a refused write must change nothing"


# --- confirm a proposed work item (PE-03, PE-07, PE-19) -------------------------------------------------------------


def test_PPL_11a_PE_07_the_assigner_confirms_and_the_server_stamps_it(people_rig):
    """Given Tilo's proposed item from u_owner's meeting, when u_owner confirms it, then 200 with the status view only,
    the stored item is open with `confirmed_by` = {u_owner, server now}, one new history entry `confirmed`, a fresh
    `updated_at`, every other field untouched (source, owner, assigned_by, created_by), and the assignee's plate has
    it."""
    rig = people_rig()
    original = _proposed_item(rig)
    rig.as_user(OWNER)
    rig.require_route(("POST", "/v1/work-items/{work_item_id}/confirm"))
    version = rig.version_of("work_items", original["id"])
    response = rig.post(f"/v1/work-items/{original['id']}/confirm")
    assert response.status_code == 200, response.text[:300]
    assert response.json() == {
        "id": original["id"],
        "title": original["title"],
        "status": "open",
        "due": original["due"],
    }
    stored = rig.stored("work_items", original["id"])
    expected = copy.deepcopy(original)
    expected.update(
        status="open",
        confirmed_by={"by": OWNER, "at": NOW},
        updated_at=NOW,
        history=original["history"] + [{"at": NOW, "by": OWNER, "change": "confirmed", "status": "open"}],
    )
    assert stored == expected and conforms("work_item.schema.json", stored)
    assert stored["source"] == original["source"], "source.ref is an immutable stamp"
    assert rig.version_of("work_items", original["id"]) == version + 1
    rig.as_user(PRIYA)
    assert [(r["ref"]["id"], r["reason"]) for r in rig.plate().json()["rows"]] == [(original["id"], "work_item")]


def test_PPL_11a_PE_03_only_the_assigner_can_confirm_and_everyone_else_gets_the_one_404(people_rig):
    """A proposed item is read by no one (PE-03): not its assignee, an attendee, a teammate, an org owner or a
    stranger can confirm it, and each gets the same 404 body as for an id that does not exist."""
    rig = people_rig()
    item = _proposed_item(rig)
    before = rig.snapshot()
    rig.require_route(("POST", "/v1/work-items/{work_item_id}/confirm"))
    bodies = set()
    for actor in (PRIYA, DEV, SAM, MEERA, "u_ghost"):
        rig.as_user(actor)
        for item_id in (item["id"], "wi_never_made"):
            response = rig.post(f"/v1/work-items/{item_id}/confirm")
            assert response.status_code == 404, (actor, item_id, response.status_code)
            bodies.add(response.text)
    assert len(bodies) == 1, bodies
    _unchanged(rig, before)


def test_PPL_11a_PE_07_a_second_confirm_changes_nothing_and_a_missing_meeting_fails_closed(people_rig):
    rig = people_rig()
    item = _proposed_item(rig)
    rig.as_user(OWNER)
    assert rig.post(f"/v1/work-items/{item['id']}/confirm").status_code == 200
    after_first = rig.snapshot()
    again = rig.post(f"/v1/work-items/{item['id']}/confirm")
    assert again.status_code in (404, 409), "an open item is not confirmed twice"
    assert rig.snapshot() == after_first, "no second `confirmed` entry, no new version"
    gone = people_rig()
    other = _proposed_item(gone)
    gone.real.meetings.delete(gone.org, "mt_q4_plan", expected_version=1)  # no meeting, no tombstone
    gone.as_user(OWNER)
    snapshot = gone.snapshot()
    assert gone.post(f"/v1/work-items/{other['id']}/confirm").status_code == 404
    assert gone.snapshot() == snapshot


@pytest.mark.parametrize(
    "body",
    [
        {"confirmed_by": {"by": "u_priya", "at": "2026-10-06T10:00:00.000Z"}},
        {"status": "done"},
        {"source": {"kind": "meeting", "ref": "mt_someone_elses#ai9", "evidence": ["u0001"]}},
        {"history": []},
        {"owner": "u_sam"},
        {"assigned_by": {"by": "u_sam", "at": "2026-10-06T10:00:00.000Z"}},
        {"title": "Something else"},
        {"updated_at": "2020-01-01T00:00:00.000Z"},
        {"flagged": False},
        {"id": "wi_other"},
        {"org_id": "org_elsewhere"},
        {"by": "u_sam"},
        [],
        "confirm",
    ],
)
def test_PPL_11a_PE_19_no_stamp_owner_source_or_history_ever_comes_from_the_body(people_rig, body):
    """A confirm takes an empty JSON object and nothing else (422): `source.ref` is an immutable stamp and a stamp is
    the actor and the clock, never a request field."""
    rig = people_rig()
    item = _proposed_item(rig)
    rig.as_user(OWNER)
    rig.require_route(("POST", "/v1/work-items/{work_item_id}/confirm"))
    before = rig.snapshot()
    response = rig.client.post(f"/v1/work-items/{item['id']}/confirm", json=body)
    assert response.status_code == 422, (body, response.status_code, response.text[:200])
    _unchanged(rig, before)
    assert rig.stored("work_items", item["id"])["source"] == item["source"]


def test_PPL_11a_PE_19_a_lost_compare_and_set_is_a_409_and_one_attempt(people_rig):
    rig = people_rig()
    item = _proposed_item(rig)
    rig.as_user(OWNER)
    rig.require_route(("POST", "/v1/work-items/{work_item_id}/confirm"))
    before = rig.snapshot()
    rig.conflicting_stores("work_items")
    response = rig.post(f"/v1/work-items/{item['id']}/confirm")
    assert response.status_code == 409 and response.json()["code"] == "version_conflict", response.text[:200]
    assert [c for c in rig.store_calls if c[:2] == ("work_item", "replace")] == [("work_item", "replace", rig.org)]
    _unchanged(rig, before)


def test_PPL_11a_PE_19_eight_racing_confirms_leave_exactly_one_confirmation(people_rig):
    rig = people_rig()
    item = _proposed_item(rig)
    rig.as_user(OWNER)
    rig.require_route(("POST", "/v1/work-items/{work_item_id}/confirm"))
    version = rig.version_of("work_items", item["id"])

    def confirm(_: int) -> int:
        with TestClient(rig.app, raise_server_exceptions=False) as client:
            return client.post(f"/v1/work-items/{item['id']}/confirm", json={}).status_code

    statuses = run_threads(8, confirm)
    assert statuses.count(200) == 1, statuses
    assert all(s in (200, 404, 409) for s in statuses), statuses
    stored = rig.stored("work_items", item["id"])
    assert [h["change"] for h in stored["history"]].count("confirmed") == 1
    assert rig.version_of("work_items", item["id"]) == version + 1


def test_PPL_11a_PE_19_an_item_with_a_huge_history_is_not_confirmable_and_cannot_stall_the_api(people_rig):
    from tilo_people.errors import PeopleInputError  # noqa: PLC0415

    rig = people_rig()
    item = _proposed_item(rig)
    big = copy.deepcopy(item)
    big["history"] = big["history"] + [pl.history_entry("A_analyst", "edited", "proposed", EARLY) for _ in range(5000)]
    rig.real.work_items.delete(rig.org, item["id"], expected_version=1)
    try:
        rig.add("work_items", big)
    except PeopleInputError:
        pytest.skip("the contract now caps work_item.history; the store refuses the record")
    rig.as_user(OWNER)
    rig.require_route(("POST", "/v1/work-items/{work_item_id}/confirm"))
    before = rig.snapshot()
    started = time.monotonic()
    response = rig.post(f"/v1/work-items/{item['id']}/confirm")
    assert time.monotonic() - started < 2.0 and response.status_code == 404
    _unchanged(rig, before)


# --- confirm a meeting's minutes (PE-05, PE-07, PE-23) --------------------------------------------------------------


def test_PPL_11a_PE_05_the_owner_confirms_the_minutes_and_that_opens_the_assignees_quote(people_rig):
    """End to end: with the minutes unconfirmed the assignee has no quote (PE-23); the owner confirms over the API
    (stamp = owner and server now); then the assignee's item route answers one shown quote."""
    case = fixture_case("transcript", "invalid", "pe23_unconfirmed_minutes")
    rig = people_rig()
    rig.seed_quote_case(case)
    assert rig.quote_request(case).status_code == 404, "unconfirmed minutes give an assignee nothing"
    rig.as_user(OWNER)
    rig.require_route(("POST", "/v1/meetings/{meeting_id}/confirm"))
    response = rig.post("/v1/meetings/mt_q4_plan/confirm")
    assert response.status_code == 200, response.text[:300]
    body = response.json()
    assert conforms("meeting.schema.json", body) and body["minutes_confirmed_by"] == {"by": OWNER, "at": NOW}
    assert rig.stored("meetings", "mt_q4_plan") == body and body["status"] == "minuted"
    rig.as_user(PRIYA)
    quote = rig.quote_request(case)
    assert quote.status_code == 200 and [q["state"] for q in quote.json()["quotes"]] == ["shown"]


def test_PPL_11a_PE_05_only_the_meeting_owner_can_confirm_its_minutes(people_rig):
    case = fixture_case("transcript", "invalid", "pe23_unconfirmed_minutes")
    rig = people_rig()
    rig.seed_quote_case(case)
    before = rig.snapshot()
    rig.require_route(("POST", "/v1/meetings/{meeting_id}/confirm"))
    bodies = set()
    for actor in (PRIYA, DEV, SAM, MEERA, "u_ghost"):
        rig.as_user(actor)
        for meeting_id in ("mt_q4_plan", "mt_never_held"):
            response = rig.post(f"/v1/meetings/{meeting_id}/confirm")
            assert response.status_code == 404, (actor, meeting_id)
            bodies.add(response.text)
    assert len(bodies) == 1
    _unchanged(rig, before)


def test_PPL_11a_PE_07_confirming_minutes_twice_is_a_409_transition_and_changes_nothing(people_rig):
    case = fixture_case("transcript", "valid", "owner_reads_quotes")  # its minutes are already confirmed by u_owner
    rig = people_rig()
    rig.seed_quote_case(case)
    rig.as_user(OWNER)
    rig.require_route(("POST", "/v1/meetings/{meeting_id}/confirm"))
    before = rig.snapshot()
    response = rig.post("/v1/meetings/mt_q4_plan/confirm")
    assert response.status_code == 409 and "transition" in response.json()["problems"], response.text[:200]
    _unchanged(rig, before)


@pytest.mark.parametrize(
    "body",
    [
        {"minutes_confirmed_by": {"by": "u_owner", "at": "2026-10-06T10:00:00.000Z"}},
        {"status": "minuted"},
        {"transcript": {"artifact_id": "art_other", "version": 1}},
        {"minutes": {"artifact_id": "art_other", "version": 1}},
        {"owner": "u_sam"},
        {"world_id": "w_someone_elses"},
        {"attestation": {"by": "u_owner", "at": "2026-10-06T10:00:00.000Z", "notice_version": "9.9.9"}},
        {"delete_transcript_after": "2099-01-01T00:00:00.000Z"},
    ],
)
def test_PPL_11a_PE_19_a_minutes_confirm_takes_no_field_from_the_body(people_rig, body):
    case = fixture_case("transcript", "invalid", "pe23_unconfirmed_minutes")
    rig = people_rig()
    rig.seed_quote_case(case)
    rig.as_user(OWNER)
    rig.require_route(("POST", "/v1/meetings/{meeting_id}/confirm"))
    before = rig.snapshot()
    assert rig.client.post("/v1/meetings/mt_q4_plan/confirm", json=body).status_code == 422
    _unchanged(rig, before)


def test_PPL_11a_PE_19_a_lost_compare_and_set_on_minutes_is_a_409(people_rig):
    case = fixture_case("transcript", "invalid", "pe23_unconfirmed_minutes")
    rig = people_rig()
    rig.seed_quote_case(case)
    rig.as_user(OWNER)
    rig.require_route(("POST", "/v1/meetings/{meeting_id}/confirm"))
    before = rig.snapshot()
    rig.conflicting_stores("meetings")
    response = rig.post("/v1/meetings/mt_q4_plan/confirm")
    assert response.status_code == 409 and response.json()["code"] == "version_conflict"
    _unchanged(rig, before)


# --- create a meeting: the attestation is the server's (PE-18, PE-19, PE-13, FR-MTG-01) -----------------------------


def test_PPL_11a_PE_18_a_created_meeting_is_stamped_by_the_server_and_has_no_world_yet(people_rig, monkeypatch):
    """Given a person of the org, when they create a meeting, then 201 and a valid meeting whose id the server
    minted, whose owner and `attestation.by` are the caller, whose `attestation.at` is the server clock and whose
    `notice_version` is the server's (`deps.NOTICE_VERSION`), with status scheduled and no world, transcript, minutes
    or confirmation; attendees are names with `user` null."""
    rig = people_rig()
    rig.add_people()
    monkeypatch.setattr(rig.deps, "NOTICE_VERSION", "2.3.4", raising=False)
    rig.as_user(PRIYA)
    rig.require_route(("POST", "/v1/meetings"))
    body = {
        "title": "Q4 planning",
        "source": "upload",
        "series": "q4_planning_weekly",
        "scheduled": {"start": "2026-10-07T09:00:00.000Z", "end": "2026-10-07T10:00:00.000Z"},
        "agenda": [{"title": "Rate sheet", "minutes": 15}],
        "attendees": [{"name": "Asha Rao"}, {"name": "Dev from Acme"}],
    }
    response = rig.post("/v1/meetings", body)
    assert response.status_code == 201, response.text[:300]
    meeting = response.json()
    assert conforms("meeting.schema.json", meeting)
    assert re.fullmatch(ID_RE["mt"], meeting["id"]) and "world_id" not in meeting
    assert (meeting["org_id"], meeting["owner"], meeting["status"]) == (rig.org, PRIYA, "scheduled")
    assert meeting["attestation"] == {"by": PRIYA, "at": NOW, "notice_version": "2.3.4"}
    assert meeting["created_at"] == NOW and meeting["ended_reason"] is None
    assert meeting["minutes_confirmed_by"] is None and meeting["transcript"] is None and meeting["minutes"] is None
    assert meeting["attendees"] == [{"name": "Asha Rao", "user": None}, {"name": "Dev from Acme", "user": None}]
    assert (meeting["title"], meeting["series"], meeting["agenda"]) == (body["title"], body["series"], body["agenda"])
    assert rig.stored("meetings", meeting["id"]) == meeting
    assert meeting["delete_transcript_after"] is None and meeting["delete_minutes_after"] is None
    again = rig.post("/v1/meetings", body).json()
    assert again["id"] != meeting["id"] and "q4" not in again["id"].lower(), "ids are minted, never derived from input"


@pytest.mark.parametrize(
    "extra",
    [
        {"id": "mt_chosen"},
        {"org_id": "org_elsewhere"},
        {"owner": "u_sam"},
        {"attestation": {"by": "u_sam", "at": "2020-01-01T00:00:00.000Z", "notice_version": "0.0.1"}},
        {"notice_version": "0.0.1"},
        {"status": "minuted"},
        {"world_id": "w_someone_elses"},
        {"minutes_confirmed_by": {"by": "u_priya", "at": "2026-10-06T10:00:00.000Z"}},
        {"transcript": {"artifact_id": "art_x", "version": 1}},
        {"minutes": {"artifact_id": "art_x", "version": 1}},
        {"created_at": "2020-01-01T00:00:00.000Z"},
        {"ended_reason": "completed"},
        {"delete_transcript_after": "2099-01-01T00:00:00.000Z"},
        {"attendees": [{"name": "Sam", "user": "u_sam"}]},
    ],
)
def test_PPL_11a_PE_19_no_id_owner_stamp_world_or_identity_comes_from_a_meeting_body(people_rig, extra):
    """The body is closed: a field the server owns is a 422 and nothing is stored. An attendee's `user` is never
    taken from a request (attendees[].user is not identity: only name resolution, PPL-20, sets it)."""
    rig = people_rig()
    rig.add_people()
    rig.as_user(PRIYA)
    rig.require_route(("POST", "/v1/meetings"))
    before = rig.snapshot()
    response = rig.client.post("/v1/meetings", json={**MEETING, **extra})
    assert response.status_code == 422, (extra, response.status_code, response.text[:200])
    _unchanged(rig, before)


def test_PPL_11a_PE_13_a_meeting_text_with_a_link_a_control_character_or_too_long_is_refused(people_rig):
    rig = people_rig()
    rig.add_people()
    rig.as_user(PRIYA)
    rig.require_route(("POST", "/v1/meetings"))
    before = rig.snapshot()
    bad_titles = (
        "Join https://example.com/room",
        "Standup on meet.google.com",
        "Call on zoom.us now",
        "Line\nbreak",
        "Tab\there",
        "x" * 121,
        "",
    )
    for title in bad_titles:
        assert rig.post("/v1/meetings", {**MEETING, "title": title}).status_code == 422, title
    for agenda in ([{"title": "see https://example.com", "minutes": 5}], [{"title": "ok", "minutes": 0}]):
        assert rig.post("/v1/meetings", {**MEETING, "agenda": agenda}).status_code == 422
    assert (
        rig.post("/v1/meetings", {**MEETING, "attendees": [{"name": "Sam at https://example.com"}]}).status_code == 422
    )
    assert rig.post("/v1/meetings", {**MEETING, "source": "zoom"}).status_code == 422
    _unchanged(rig, before)


def test_PPL_11a_SEC_01_a_secret_is_redacted_before_check_write_so_it_can_never_be_stored_or_echoed(people_rig, caplog):
    """The secret redactor runs on every text field BEFORE the schema check. The title below is 100 characters plus a
    54-character fake token: 154 characters, over the 120 cap, so only a redact-first order lets it through (as 110
    characters ending `[REDACTED]`). Neither the token nor the title is logged."""
    secret = fake_token()
    caplog.set_level(logging.DEBUG)
    rig = people_rig()
    rig.add_people()
    rig.as_user(PRIYA)
    rig.require_route(("POST", "/v1/meetings"))
    title = "t" * 100 + secret
    response = rig.post(
        "/v1/meetings",
        {
            "title": title,
            "source": "bot",
            "agenda": [{"title": f"agenda {secret}", "minutes": 5}],
            "attendees": [{"name": f"Guest {secret}"}],
        },
    )
    assert response.status_code == 201, response.text[:300]
    stored = rig.stored("meetings", response.json()["id"])
    assert secret not in str(stored) and secret not in response.text
    assert stored["title"] == "t" * 100 + "[REDACTED]"
    assert stored["agenda"][0]["title"] == "agenda [REDACTED]" and stored["attendees"][0]["name"] == "Guest [REDACTED]"
    assert any(secret in call for call in rig.redactor.calls), "the redactor saw the text"
    assert secret not in "\n".join(r.getMessage() for r in caplog.records)


def test_PPL_11a_PE_18_only_a_person_of_the_org_creates_a_meeting_and_a_refusal_stores_nothing(people_rig):
    rig = people_rig()
    rig.add_people()
    rig.require_route(("POST", "/v1/meetings"))
    before = rig.snapshot()
    rig.as_user("u_ghost")
    assert rig.post("/v1/meetings", MEETING).status_code == 403
    _unchanged(rig, before)


# --- create a person: the id is minted by the server (PE-17, G1) ----------------------------------------------------


def test_PPL_11a_PE_17_an_org_owner_creates_a_person_with_a_minted_id_and_gets_the_membership_view_back(people_rig):
    """Given an org owner, when they create a person, then 201 with the membership view only (id, display name, org
    role, memberships: no email, aliases, zone or channel, PE-20); the stored person is a member with no team, in the
    served org, stamped {owner, now}; the id is minted, distinct on every call and never built from the input; and the
    new person can then sign in to an (empty) plate."""
    rig = people_rig()
    rig.add_people()
    rig.as_user(OWNER)
    rig.require_route(("POST", "/v1/people"))
    first = rig.post("/v1/people", PERSON)
    assert first.status_code == 201, first.text[:300]
    view = first.json()
    assert set(view) == {"id", "display_name", "org_role", "memberships"}
    assert (view["display_name"], view["org_role"], view["memberships"]) == ("Nina Patel", "member", [])
    assert (
        re.fullmatch(ID_RE["u"], view["id"]) and "nina" not in view["id"].lower() and "patel" not in view["id"].lower()
    )
    stored = rig.stored("persons", view["id"])
    assert conforms("person.schema.json", stored)
    assert stored == {
        "id": view["id"],
        "org_id": rig.org,
        **PERSON,
        "org_role": "member",
        "memberships": [],
        "created_by": {"by": OWNER, "at": NOW},
    }
    second = rig.post("/v1/people", PERSON).json()
    assert second["id"] != view["id"], "the same input twice is two people with two ids"
    rig.as_user(view["id"])
    plate = rig.plate()
    assert plate.status_code == 200 and plate.json()["rows"] == [] and plate.json()["user"] == view["id"]


@pytest.mark.parametrize(
    "extra",
    [
        {"id": "u_chosen"},
        {"org_id": "org_elsewhere"},
        {"org_role": "owner"},
        {"memberships": [{"team": "tm_launch", "assigned_by": {"by": "u_owner", "at": "2026-10-05T09:00:00.000Z"}}]},
        {"created_by": {"by": "u_sam", "at": "2020-01-01T00:00:00.000Z"}},
        {"user_id": "u_chosen"},
    ],
)
def test_PPL_11a_PE_17_a_person_body_cannot_choose_the_id_the_org_the_role_or_a_team(people_rig, extra):
    """The org never comes from input (PE-17), nor does the id, the role (roles are only ever promoted, by another
    ticket), a membership or a stamp: 422 and nothing stored."""
    rig = people_rig()
    rig.add_people()
    rig.as_user(OWNER)
    rig.require_route(("POST", "/v1/people"))
    before = rig.snapshot()
    response = rig.client.post("/v1/people", json={**PERSON, **extra})
    assert response.status_code == 422, (extra, response.status_code)
    _unchanged(rig, before)


def test_PPL_11a_PE_17_only_an_org_owner_of_the_served_org_creates_people(people_rig):
    rig = people_rig()
    rig.add_people()
    rig.require_route(("POST", "/v1/people"))
    before = rig.snapshot()
    for actor in (PRIYA, DEV, SAM, "u_ghost"):  # members and a stranger; u_meera is an org owner
        rig.as_user(actor)
        response = rig.post("/v1/people", PERSON)
        assert response.status_code == 403, (actor, response.status_code)
    _unchanged(rig, before)
    rig.as_user(MEERA)
    assert rig.post("/v1/people", PERSON).status_code == 201, "any org owner, not only the first"


def test_PPL_11a_PE_20_a_bad_person_body_is_a_422(people_rig):
    rig = people_rig()
    rig.add_people()
    rig.as_user(OWNER)
    rig.require_route(("POST", "/v1/people"))
    before = rig.snapshot()
    bad = (
        {**PERSON, "email": "not an address"},
        {**PERSON, "display_name": ""},
        {**PERSON, "display_name": "x" * 81},
        {**PERSON, "time_zone": "not a zone"},
        {**PERSON, "preferred_channel": "whatsapp"},
        {**PERSON, "aliases": ["a"] * 9},
        {k: v for k, v in PERSON.items() if k != "email"},
    )
    for body in bad:
        assert rig.client.post("/v1/people", json=body).status_code == 422, body
    _unchanged(rig, before)


# --- create a person-made work item: mail and request sources must be the caller's own (PE-08, FR-PA-01) ------------


def test_PPL_11a_FR_PA_01_a_person_adds_their_own_item_and_code_computes_its_due_date(people_rig):
    """The item is the caller's own: owner = caller, `created_by` {person, caller, now}, open, no assigner, a history
    of one `created` entry, `due` computed by code from `due_text` in the caller's zone (never from the body)."""
    from tilo_people.dates import resolve_due  # noqa: PLC0415

    rig = people_rig()
    rig.add_people()
    rig.as_user(PRIYA)
    rig.require_route(("POST", "/v1/work-items"))
    for phrase in ("tomorrow", "by Friday", "next Friday", "whenever", None):
        resolved = resolve_due(phrase, meeting_at=NOW, time_zone="Asia/Kolkata")
        response = rig.post(
            "/v1/work-items",
            {"title": "Water the plants", "due_text": phrase, "source": {"kind": "manual", "ref": None}},
        )
        assert response.status_code == 201, (phrase, response.text[:300])
        item = response.json()
        assert conforms("work_item.schema.json", item) and item == rig.stored("work_items", item["id"])
        assert re.fullmatch(ID_RE["wi"], item["id"])
        assert (item["due"], item["due_text"]) == (resolved.due, resolved.due_text), phrase
        assert (item["owner"], item["org_id"], item["status"], item["flagged"]) == (PRIYA, rig.org, "open", False)
        assert item["created_by"] == {"by": "person", "ref": PRIYA, "at": NOW}
        assert (item["assigned_by"], item["confirmed_by"], item["snoozed_until"]) == (None, None, None)
        assert item["history"] == [{"at": NOW, "by": PRIYA, "change": "created", "status": "open"}]
        assert (item["created_at"], item["updated_at"]) == (NOW, NOW)
        assert item["source"] == {"kind": "manual", "ref": None, "evidence": []}
    plate = rig.plate().json()
    assert len(plate["rows"]) == 5 and {r["reason"] for r in plate["rows"]} == {"work_item"}


@pytest.mark.parametrize(
    "extra",
    [
        {"id": "wi_chosen"},
        {"org_id": "org_elsewhere"},
        {"owner": "u_sam"},
        {"due": "2026-10-09"},
        {"status": "done"},
        {"created_by": {"by": "tilo", "ref": "A_analyst", "at": "2026-10-06T10:00:00.000Z"}},
        {"assigned_by": {"by": "u_owner", "at": "2026-10-06T10:00:00.000Z"}},
        {"confirmed_by": {"by": "u_owner", "at": "2026-10-06T10:00:00.000Z"}},
        {"history": []},
        {"flagged": True},
        {"snoozed_until": "2026-10-07T10:00:00.000Z"},
        {"created_at": "2020-01-01T00:00:00.000Z"},
    ],
)
def test_PPL_11a_PE_03_nobody_pushes_an_item_onto_another_person_and_no_stamp_or_due_comes_from_the_body(
    people_rig, extra
):
    rig = people_rig()
    rig.add_people()
    rig.as_user(PRIYA)
    rig.require_route(("POST", "/v1/work-items"))
    before = rig.snapshot()
    response = rig.client.post(
        "/v1/work-items", json={"title": "Do it", "source": {"kind": "manual", "ref": None}, **extra}
    )
    assert response.status_code == 422, (extra, response.status_code, response.text[:200])
    _unchanged(rig, before)


@pytest.mark.parametrize(
    "source",
    [
        {"kind": "meeting", "ref": "mt_q4_plan#ai1"},
        {"kind": "pinboard", "ref": "pb_q4_deadline"},
        {"kind": "manual", "ref": "wi_something"},
        {"kind": "mail", "ref": None},
        {"kind": "request", "ref": None},
        {"kind": "mail", "ref": "m_own", "evidence": ["u0021"]},
        {"kind": "telepathy", "ref": None},
    ],
)
def test_PPL_11a_PE_08_a_person_cannot_claim_a_machine_source_or_cite_evidence(people_rig, source):
    rig = people_rig()
    rig.add_people()
    rig.owners.owners[("mail", "m_own")] = PRIYA
    rig.as_user(PRIYA)
    rig.require_route(("POST", "/v1/work-items"))
    before = rig.snapshot()
    response = rig.client.post("/v1/work-items", json={"title": "Do it", "source": source})
    assert response.status_code == 422, (source, response.status_code, response.text[:200])
    _unchanged(rig, before)


@pytest.mark.parametrize("kind", ["mail", "request"])
def test_PPL_11a_PE_08_a_mail_or_request_source_must_belong_to_the_caller_and_a_stranger_cannot_probe_for_ids(
    people_rig, kind
):
    """An item tracked from mail or a request: `source_owner == actor` is checked server side against the mail and
    request owners. Someone else's id and an id that does not exist give the same 422 body (no id oracle)."""
    rig = people_rig()
    rig.add_people()
    rig.owners.owners.update({(kind, "own_one"): PRIYA, (kind, "sams_one"): SAM, (kind, "owners_one"): OWNER})
    rig.as_user(PRIYA)
    rig.require_route(("POST", "/v1/work-items"))
    ok = rig.post("/v1/work-items", {"title": "Reply to the supplier", "source": {"kind": kind, "ref": "own_one"}})
    assert ok.status_code == 201, ok.text[:300]
    assert ok.json()["source"] == {"kind": kind, "ref": "own_one", "evidence": []}
    assert ok.json()["created_by"] == {"by": "person", "ref": PRIYA, "at": NOW}
    before = rig.snapshot()
    bodies = set()
    for ref in ("sams_one", "owners_one", "never_existed"):
        response = rig.post("/v1/work-items", {"title": "Steal it", "source": {"kind": kind, "ref": ref}})
        assert response.status_code == 422, (ref, response.status_code)
        bodies.add(response.text)
    assert len(bodies) == 1, "someone else's id and a missing id must be indistinguishable"
    _unchanged(rig, before)
    assert all(call[0] == kind for call in rig.owners.calls)


def test_PPL_11a_PE_08_only_a_person_of_the_org_creates_items_and_titles_are_redacted_first(people_rig):
    secret = fake_token()
    rig = people_rig()
    rig.add_people()
    rig.require_route(("POST", "/v1/work-items"))
    before = rig.snapshot()
    rig.as_user("u_ghost")
    assert rig.post("/v1/work-items", {"title": "x", "source": {"kind": "manual", "ref": None}}).status_code == 403
    _unchanged(rig, before)
    rig.as_user(PRIYA)
    response = rig.post("/v1/work-items", {"title": "k" * 100 + secret, "source": {"kind": "manual", "ref": None}})
    assert response.status_code == 201, "154 characters before redaction, 110 after: redact first"
    assert secret not in response.text and response.json()["title"] == "k" * 100 + "[REDACTED]"
    assert (
        rig.post("/v1/work-items", {"title": "k" * 141, "source": {"kind": "manual", "ref": None}}).status_code == 422
    )


# --- every write is JSON only ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/v1/meetings",
        "/v1/people",
        "/v1/work-items",
        "/v1/meetings/mt_q4_plan/confirm",
        "/v1/work-items/wi_rate_sheet/confirm",
    ],
)
def test_PPL_11a_SEC_05_a_write_reads_only_application_json_so_a_cross_site_form_post_does_nothing(people_rig, path):
    """A hostile page can post urlencoded, multipart and text/plain cross-site without a preflight (the task routes
    answer 415 for the same reason). The writes do too, and nothing is stored."""
    case = fixture_case("transcript", "invalid", "pe23_unconfirmed_minutes")
    rig = people_rig()
    rig.seed_quote_case(case)
    rig.add("work_items", own_item("wi_own1", OWNER))
    rig.as_user(OWNER)
    before = rig.snapshot()
    for kwargs in (
        {"data": {"title": "x", "source": "upload"}},
        {"files": {"title": (None, "x")}},
        {"content": '{"title": "x", "source": "upload"}', "headers": {"content-type": "text/plain"}},
        {"content": "{}", "headers": {"content-type": "application/x-www-form-urlencoded"}},
    ):
        response = rig.client.post(path, **kwargs)
        assert response.status_code == 415, (path, list(kwargs), response.status_code)
    _unchanged(rig, before)
