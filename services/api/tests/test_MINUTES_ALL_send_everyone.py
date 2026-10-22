"""MINUTES-ALL (owner, 21 Oct): "send the meeting minutes and transcripts to all those that joined". The Owner reviews a
send list (themself, the record's attendees with the address on their person record or "no email on file", and the
people heard in the call by name only: an address is never guessed from a name), edits it, and drafts ONE email with
the minutes and, if asked, the screened transcript appended after the checked minutes. It is the existing T3 card:
nothing is sent until the Owner approves it in Needs you. Offline doubles, the real HTTP chain."""

import json

import pytest
from _ppl11a_lib import OWNER, PRIYA, SAM
from test_FR_MTG_03_04_08_minutes_chain import analyze_confirm, chain, no_preview, post, rows, stored  # noqa: F401
from test_FR_MTG_03_analysis_publication import integration  # noqa: F401
from test_FR_MTG_03_owner_analysis_mode import owner_call  # noqa: F401
from test_FR_MTG_03_owner_minutes_caller import caller_app  # noqa: F401
from tilo_api import deps, meeting_followup
from tilo_memory.artifacts import Scope

LIST = "/v1/meetings/mt_q4_plan/followup-recipients"


def with_guest(c):
    """An attendee the meeting named who has no person record: their address is not on file."""
    current = c.rig.real.meetings.get(c.rig.org, "mt_q4_plan")
    attendees = [*current.record["attendees"], {"name": "Visiting Guest", "user": None}]
    c.rig.real.meetings.replace({**current.record, "attendees": attendees}, expected_version=current.version)


def speakers(c):
    m = stored(c)
    data = c.rig.artifacts.read(Scope(c.rig.org, m["world_id"], OWNER), m["transcript"])
    return list(dict.fromkeys(u["speaker"] for u in json.loads(data)["utterances"]))


def test_MINUTES_ALL_the_send_list_names_everyone_and_never_guesses_an_address(chain):  # noqa: F811
    c = chain
    with_guest(c)
    analyze_confirm(c)
    response = c.client.get(LIST, headers=c.headers)
    assert response.status_code == 200, response.text
    body = response.json()
    owner_mail = c.rig.real.persons.get(c.rig.org, OWNER).record["email"].lower()
    rows_ = body["recipients"]
    assert rows_[0] == {"name": "Me", "email": owner_mail, "source": "owner"}
    assert {"name": "Visiting Guest", "email": None, "source": "invited"} in rows_
    linked = {a["name"]: a["user"] for a in stored(c)["attendees"]}
    for row in rows_:
        if row["source"] == "invited":  # an address exactly when the attendee has a person record
            assert (row["email"] is not None) == (linked[row["name"]] is not None), row["name"]
        if row["source"] == "heard":
            assert row["email"] is None  # a name heard in the call never becomes an address
    named = {r["name"].casefold() for r in rows_}
    owner_names = {a["name"].casefold() for a in stored(c)["attendees"] if a["user"] == OWNER}
    owner_names.add(c.rig.real.persons.get(c.rig.org, OWNER).record["display_name"].casefold())
    heard = [s for s in speakers(c) if s.casefold() not in owner_names | {"tilo"}]  # the Owner's own voice is "Me"
    assert heard and all(s.casefold() in named for s in heard)
    assert body["transcript"] is True and response.headers["cache-control"] == "no-store"


def test_MINUTES_ALL_a_bot_meeting_lists_the_people_heard_with_no_email_on_file(chain):  # noqa: F811
    c = chain
    current = c.rig.real.meetings.get(c.rig.org, "mt_q4_plan")
    c.rig.real.meetings.replace({**current.record, "attendees": []}, expected_version=current.version)  # a link meeting
    analyze_confirm(c)
    rows_ = c.client.get(LIST, headers=c.headers).json()["recipients"]
    heard = [r for r in rows_ if r["source"] == "heard"]
    owner = c.rig.real.persons.get(c.rig.org, OWNER).record["display_name"].casefold()
    assert heard and all(r["email"] is None for r in heard)
    assert {r["name"] for r in heard} == {s for s in speakers(c) if s.casefold() not in {owner, "tilo"}}


def test_MINUTES_ALL_one_email_to_the_reviewed_addresses_with_the_transcript_waits_for_approval(chain):  # noqa: F811
    c = chain
    analyze_confirm(c)
    owner_mail = c.rig.real.persons.get(c.rig.org, OWNER).record["email"].lower()
    response = post(c, "draft-followup", {"addresses": [owner_mail, "Guest.Person@Example.org"], "transcript": True})
    assert response.status_code == 200, response.text
    preview = response.json()
    assert (preview["tier"], preview["status"]) == ("T3", "ready") and preview["options"] == ["send", "edit", "cancel"]
    assert sorted(preview["to"]) == sorted([owner_mail, "guest.person@example.org"])
    assert "Transcript, as Tilo captured it in the meeting (not checked):" in preview["body"]
    first = json.loads(c.rig.artifacts.read(Scope(c.rig.org, stored(c)["world_id"], OWNER), stored(c)["transcript"]))
    assert first["utterances"][0]["text"].split()[0] in preview["body"]
    assert deps.get_outbox_store().all_entries() == []  # nothing sent: the Owner approves the card in Needs you
    assert rows(c, "followup_drafts") and rows(c, "cards")


def test_MINUTES_ALL_without_the_transcript_the_mail_has_only_the_minutes(chain):  # noqa: F811
    c = chain
    analyze_confirm(c)
    response = post(c, "draft-followup", {"addresses": ["guest@example.org"]})
    assert response.status_code == 200, response.text
    assert "Transcript, as Tilo captured it" not in response.json()["body"]


def test_MINUTES_ALL_an_address_that_is_not_one_bare_mailbox_is_refused_before_any_draft(chain):  # noqa: F811
    c = chain
    analyze_confirm(c)
    for bad in (["Guest <guest@example.org>"], ["a@b"], ["guest@example.org, other@example.org"], ["x@exa mple.org"]):
        response = post(c, "draft-followup", {"addresses": bad})
        assert response.status_code == 422, (bad, response.text)
    assert post(c, "draft-followup", {"transcript": True}).status_code == 422  # the transcript rides on a mail only
    no_preview(c)


def test_MINUTES_ALL_REVIEW_two_attendees_who_share_a_name_are_both_listed_by_their_own_address(chain):  # noqa: F811
    """Security review fix 5: attendees are told apart by name AND address, so a shared name never drops a person."""
    c = chain
    current = c.rig.real.meetings.get(c.rig.org, "mt_q4_plan")
    kept = [a for a in current.record["attendees"] if a["user"] == OWNER]
    twins = [{"name": "Alex Lee", "user": PRIYA}, {"name": "Alex Lee", "user": SAM}]
    c.rig.real.meetings.replace({**current.record, "attendees": kept + twins}, expected_version=current.version)
    analyze_confirm(c)
    mails = {c.rig.real.persons.get(c.rig.org, u).record["email"].lower() for u in (PRIYA, SAM)}
    assert len(mails) == 2  # setup guard: two people, two addresses
    rows_ = c.client.get(LIST, headers=c.headers).json()["recipients"]
    alexes = [r for r in rows_ if r["name"] == "Alex Lee"]
    assert [r["source"] for r in alexes] == ["invited", "invited"]
    assert {r["email"] for r in alexes} == mails


@pytest.mark.parametrize("screening", ["flagged", "unscreened"])
def test_MINUTES_ALL_REVIEW_a_transcript_that_is_not_clean_is_never_attached(chain, monkeypatch, screening):  # noqa: F811
    """Security review fix 2: asking for a flagged (or unscreened) transcript is a 409 and no draft at all."""
    c = chain
    analyze_confirm(c)
    real = meeting_followup.meeting_transcript
    monkeypatch.setattr(
        meeting_followup, "meeting_transcript", lambda reader, mid: {**real(reader, mid), "screening": screening}
    )
    response = post(c, "draft-followup", {"addresses": ["guest@example.org"], "transcript": True})
    assert (response.status_code, response.json()["detail"]) == (409, "transcript_unavailable")
    no_preview(c)


def test_MINUTES_ALL_the_send_list_is_the_owners_alone(chain):  # noqa: F811
    c = chain
    analyze_confirm(c)
    c.writer.actor = SAM
    assert c.client.get(LIST, headers=c.headers).status_code == 404
