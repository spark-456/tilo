"""Email resolution is code-owned and bounded by the meeting owner's current team directory."""

import copy

import pytest
from _mtg09b_lib import HostRig
from _ppl11a_lib import ATTEST, EARLY, NOW, OTHER_ORG, OWNER, PRIYA, SAM, conforms
from _ppl11c_lib import meeting_rig


def _write(rig, operation, attendees):
    if operation == "create":
        return rig.post("/v1/meetings", {**ATTEST, "title": "Planning", "source": "upload", "attendees": attendees})
    return rig.post("/v1/meetings/mt_q4_plan/edit", {"attendees": attendees})


def _replace(rig, person):
    rig.real.persons.replace(person, expected_version=rig.version_of("persons", person["id"]))


@pytest.mark.parametrize("operation", ["create", "edit"])
def test_FR_MTG_08_PE_15_exact_email_links_self_and_teammates_without_storing_address_fields(people_rig, operation):
    rig = meeting_rig(people_rig)
    attendees = [
        {"name": "PRIYA@EXAMPLE.COM"},
        {"name": "My caption", "email": "ASHA@EXAMPLE.COM"},
        {"name": "New caption", "email": "priya@example.com"},
        {"name": "Priya Nair"},
        {"name": "Guest", "email": "unknown@example.com"},
        {"name": "sam@example.com"},  # same org, outside the owner's team
        {"name": "prefix priya@example.com"},  # exact address only
    ]
    response = _write(rig, operation, attendees)
    assert response.status_code == (201 if operation == "create" else 200), response.text
    record = response.json()
    assert conforms("meeting.schema.json", record)
    assert record["attendees"] == [
        {"name": a["name"], "user": user}
        for a, user in zip(attendees, [PRIYA, OWNER, PRIYA, None, None, None, None], strict=True)
    ]
    assert all(set(a) == {"name", "user"} for a in record["attendees"])


@pytest.mark.parametrize("operation", ["create", "edit"])
@pytest.mark.parametrize("membership", ["pending", "accepted", "lapsed", "future", "other_org"])
def test_FR_MTG_08_PE_15_email_resolution_obeys_ADR_0044_membership(people_rig, operation, membership):
    rig = meeting_rig(people_rig)
    owner = copy.deepcopy(rig.stored("persons", OWNER))
    owner["org_role"] = "member"
    owner["memberships"] = [{"team": "tm_self", "lead": True, "assigned_by": {"by": OWNER, "at": EARLY}}]
    if membership == "lapsed":
        owner["memberships"] = []
    _replace(rig, owner)
    target = copy.deepcopy(rig.stored("persons", PRIYA))
    target["memberships"] = [{"team": "tm_self", "assigned_by": {"by": OWNER, "at": "2026-10-05T10:00:00.000Z"}}]
    if membership != "pending":
        target["memberships"][0]["accepted_at"] = "2026-10-07T10:00:00.000Z" if membership == "future" else NOW
    if membership == "other_org":
        rig.real.persons.delete(rig.org, PRIYA, expected_version=rig.version_of("persons", PRIYA))
        target["org_id"] = OTHER_ORG
        rig.real.persons.create(target)
    else:
        _replace(rig, target)
    result = _write(rig, operation, [{"name": "priya@example.com"}])
    assert result.status_code == (201 if operation == "create" else 200), result.text
    assert result.json()["attendees"] == [
        {"name": "priya@example.com", "user": PRIYA if membership == "accepted" else None}
    ]


@pytest.mark.parametrize("operation", ["create", "edit"])
def test_FR_MTG_08_PE_15_client_user_is_refused_and_invalid_email_is_not_an_oracle(people_rig, operation):
    rig = meeting_rig(people_rig)
    before = rig.snapshot()
    for attendee in ({"name": "Priya", "user": SAM}, {"name": "Priya", "email": "not an address"}):
        assert _write(rig, operation, [attendee]).status_code == 422
    assert rig.snapshot() == before


def test_FR_MTG_08_PE_15_edit_keeps_legacy_links_and_re_resolves_unlinked_email(people_rig):
    rig = meeting_rig(people_rig)
    meeting = rig.stored("meetings", "mt_q4_plan")
    meeting["attendees"].append({"name": "priya@example.com", "user": None})
    rig.real.meetings.replace(meeting, expected_version=rig.version_of("meetings", meeting["id"]))
    response = _write(rig, "edit", [{"name": "Priya"}, {"name": "priya@example.com"}])
    assert response.status_code == 200
    assert response.json()["attendees"] == [
        {"name": "Priya", "user": PRIYA},
        {"name": "priya@example.com", "user": PRIYA},
    ]


def test_FR_MTG_08_PE_15_unauthorized_edit_never_lists_the_directory(people_rig):
    rig = meeting_rig(people_rig)
    rig.as_user(SAM)
    rig.store_calls.clear()
    assert _write(rig, "edit", [{"name": "priya@example.com"}]).status_code == 404
    assert ("person", "list", rig.org) not in rig.store_calls


def test_FR_MTG_08_PE_15_email_matches_before_redaction_and_only_sanitized_name_is_stored(people_rig):
    rig = meeting_rig(people_rig)
    rig.redactor = lambda text: text.replace("priya@example.com", "[removed]")
    response = _write(rig, "create", [{"name": "priya@example.com"}])
    assert response.status_code == 201
    assert response.json()["attendees"] == [{"name": "[removed]", "user": PRIYA}]


def test_FR_MTG_PE_15_create_refuses_unknown_actor_before_directory_list(people_rig):
    rig = meeting_rig(people_rig)
    rig.as_user("u_absent")
    rig.store_calls.clear()
    response = _write(rig, "create", [{"name": "priya@example.com"}])
    assert response.status_code == 403
    assert ("person", "list", rig.org) not in rig.store_calls


def test_FR_MTG_PE_15_cleaned_email_name_is_resolved(people_rig):
    rig = meeting_rig(people_rig)
    response = _write(rig, "create", [{"name": "pri\u200bya@example.com"}])
    assert response.status_code == 201
    assert response.json()["attendees"] == [{"name": "priya@example.com", "user": PRIYA}]


def test_FR_MTG_PE_15_edit_drops_link_after_teammate_leaves(people_rig):
    rig = meeting_rig(people_rig)
    target = rig.stored("persons", PRIYA)
    target["memberships"] = []
    _replace(rig, target)
    response = _write(rig, "edit", [{"name": "Priya"}])
    assert response.status_code == 200
    assert response.json()["attendees"] == [{"name": "Priya", "user": None}]


@pytest.mark.parametrize("state", ["left_team", "missing", "other_org"])
def test_FR_MTG_PE_15_host_drops_stale_attendee_link(people_rig, monkeypatch, state):
    from tilo_api import meeting_host

    hr = HostRig(people_rig())
    target = hr.rig.stored("persons", PRIYA)
    if state == "left_team":
        target["memberships"] = []
        _replace(hr.rig, target)
    else:
        hr.rig.real.persons.delete(hr.rig.org, PRIYA, expected_version=hr.rig.version_of("persons", PRIYA))
        if state == "other_org":
            target["org_id"] = OTHER_ORG
            hr.rig.real.persons.create(target)
    seen = []
    original = meeting_host.draft_meeting_event

    def capture(*, meeting, **kwargs):
        seen.extend(meeting["attendees"])
        return original(meeting=meeting, **kwargs)

    monkeypatch.setattr(meeting_host, "draft_meeting_event", capture)
    response = hr.host()
    assert response.status_code == 200, response.text
    hr.wait_gate()
    assert next(a for a in seen if a["name"] == "Priya")["user"] is None
