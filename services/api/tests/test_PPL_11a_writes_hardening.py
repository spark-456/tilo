"""PPL-11a slice C hardening (security review): the writes clean a person's text before the secret redactor and the
schema, never echo a key the caller invented, redact `series` like every other text, and refuse an over-long `due_text`
instead of dropping it. Code points are built with `u()` (no escape sequences in test files)."""

from __future__ import annotations

from _ppl11a_lib import ATTEST, OWNER, PRIYA, fake_token, u

MEETING = {"title": "Weekly sync", "source": "upload", **ATTEST}
ITEM = {"title": "Water the plants", "source": {"kind": "manual", "ref": None}}
PERSON = {
    "display_name": "Nina Patel",
    "aliases": [],
    "email": "nina.patel@example.com",
    "time_zone": "Asia/Kolkata",
    "preferred_channel": "web",
}
HIDDEN = u(0x202E, 0x200B, 0x2028, 0x85, 0x2029, 0xFEFF)  # bidi override, zero width, separators, NEL, BOM


def test_PPL_11a_PE_24_hidden_format_and_separator_characters_are_cleaned_from_every_stored_text(people_rig):
    """A title, an agenda title, an attendee, a series, a display name, an alias and an item title lose U+202E, U+2028,
    U+0085 and U+200B before they are redacted, checked and stored."""
    rig = people_rig()
    rig.add_people()
    rig.as_user(PRIYA)
    meeting = rig.post(
        "/v1/meetings",
        {
            **ATTEST,
            "title": f"Pl{HIDDEN}an Q4",
            "source": "bot",
            "series": f"q4{HIDDEN}-plan",
            "agenda": [{"title": f"Rate{HIDDEN} sheet", "minutes": 5}],
            "attendees": [{"name": f"As{HIDDEN}ha"}],
        },
    )
    assert meeting.status_code == 201, meeting.text[:300]
    stored = rig.stored("meetings", meeting.json()["id"])
    assert (stored["title"], stored["series"]) == ("Plan Q4", "q4-plan")
    assert stored["agenda"][0]["title"] == "Rate sheet" and stored["attendees"][0]["name"] == "Asha"
    item = rig.post("/v1/work-items", {**ITEM, "title": f"Wa{HIDDEN}ter", "due_text": f"to{HIDDEN}morrow"})
    assert item.status_code == 201 and item.json()["title"] == "Water" and item.json()["due_text"] == "tomorrow"
    assert item.json()["due"] is not None, "the cleaned phrase is the one resolved"
    rig.as_user(OWNER)
    person = rig.post("/v1/people", {**PERSON, "display_name": f"Ni{HIDDEN}na", "aliases": [f"N{HIDDEN}i"]})
    assert person.status_code == 201 and person.json()["display_name"] == "Nina"
    assert rig.stored("persons", person.json()["id"])["aliases"] == ["Ni"]
    assert all(HIDDEN[0] not in call and HIDDEN[1] not in call for call in rig.redactor.calls), "cleaned first"


def test_PPL_11a_PE_13_a_link_hidden_with_a_zero_width_character_is_still_refused(people_rig):
    rig = people_rig()
    rig.add_people()
    rig.as_user(PRIYA)
    before = rig.snapshot()
    for title in (
        f"https:{u(0x200B)}//evil.example/x",
        f"https{u(0x202E)}://evil.example",
        f"meet.google{u(0x200B)}.com",
    ):
        assert rig.post("/v1/meetings", {**MEETING, "title": title}).status_code == 422, title
    assert (
        rig.post("/v1/meetings", {**MEETING, "attendees": [{"name": f"x https:{u(0x2063)}//e.example"}]}).status_code
        == 422
    )
    assert rig.snapshot() == before


def test_PPL_11a_SEC_01_an_unknown_body_key_is_never_echoed_back(people_rig):
    """A key the caller made up (a fake token used as a key, at the top or nested) is not in the 422 body."""
    secret = fake_token()
    rig = people_rig()
    rig.add_people()
    for actor, path, body in (
        (PRIYA, "/v1/meetings", {**MEETING, secret: 1}),
        (PRIYA, "/v1/meetings", {**MEETING, "attendees": [{"name": "Sam", secret: 1}]}),
        (PRIYA, "/v1/work-items", {**ITEM, "source": {**ITEM["source"], secret: 1}}),
        (OWNER, "/v1/people", {**PERSON, secret: 1}),
        (OWNER, "/v1/meetings/mt_x/confirm", {secret: 1}),
    ):
        rig.as_user(actor)
        response = rig.client.post(path, json=body)
        assert response.status_code == 422, (path, response.status_code)
        assert secret not in response.text and secret[:8] not in response.text, path


def test_PPL_11a_SEC_01_a_series_goes_through_the_redactor_like_every_other_text(people_rig):
    secret = fake_token()
    rig = people_rig()
    rig.add_people()
    rig.as_user(PRIYA)
    before = rig.snapshot()
    ok = rig.post("/v1/meetings", {**MEETING, "series": "weekly_review"})
    assert ok.status_code == 201 and "weekly_review" in rig.redactor.calls
    rig.redactor.calls.clear()
    response = rig.post("/v1/meetings", {**MEETING, "series": f"q4_{secret}"})
    assert response.status_code == 422, "the redactor ran first, and its output is not a series"
    assert any(secret in call for call in rig.redactor.calls) and secret not in response.text
    assert secret not in str(rig.stored("meetings", ok.json()["id"])) and rig.snapshot() != before


def test_PPL_11a_FR_PA_01_a_due_text_over_sixty_characters_is_a_422_not_a_quiet_null(people_rig):
    rig = people_rig()
    rig.add_people()
    rig.as_user(PRIYA)
    assert rig.post("/v1/work-items", {**ITEM, "due_text": "x" * 60}).status_code == 201
    before = rig.snapshot()
    for phrase in ("x" * 61, "by next " + "friday " * 20):
        response = rig.post("/v1/work-items", {**ITEM, "due_text": phrase})
        assert response.status_code == 422, (len(phrase), response.status_code)
    assert rig.snapshot() == before
