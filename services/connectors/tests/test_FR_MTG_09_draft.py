"""FR-MTG-09 (d) bounds, MH-01 to MH-07: `draft_meeting_event` and `host_gate` (steps 3 and 4 of the ordered flow).
API_FR_MTG_09.md "`tilo_connectors.meeting_host`" and "Acceptance tests (d)"; ADR-0024 decision 3 (who is invited),
PE-05, PE-09, PE-14, PE-18, PE-20, PE-21; BQ-MTG09-6 (invitees), BQ-MTG09-9 (60 minutes).

Pure and offline: no side effect, no network, no model. Every test fails today with
ModuleNotFoundError: tilo_connectors.meeting_host.
"""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import inspect
import json
import re

import pytest
from _meeting_host_lib import (
    ACTION_TYPE,
    ASHA,
    ATTACKER,
    CONNECTOR_ID,
    EXACT_MAX,
    EXTRA_MAIL,
    IST,
    MEETING_ID,
    OTHER_ORG,
    OWNER,
    PRIYA_MAIL,
    SAM_MAIL,
    T_END,
    T_NOW,
    T_START,
    DraftArtifacts,
    attendee,
    build_card,
    default_persons,
    draft_of,
    errs,
    host_config,
    host_decl,
    local_when,
    many_users,
    meeting,
    mh,
    minutes_after,
    no_network_and_no_live,  # noqa: F401 - autouse guard
    oracle_content,
    oracle_exact,
    person,
    refusal_rule,
    write_personal,
    write_registry,
)
from _oauth_lib import schema_errors
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from tilo_policy import SideEffectFacts, load_risk_table

PROPERTY = settings(
    max_examples=60,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],  # the autouse network guard
)

# ---------------------------------------------------------------------------
# The draft: who is invited, what the bytes are, what the card will say


def test_FR_MTG_09_MH_03_recipients_are_the_owner_then_attendee_users_in_attendee_order():
    draft = draft_of()

    assert draft.recipients == (ASHA, PRIYA_MAIL, SAM_MAIL)
    assert draft.invited == (OWNER, "u_priya", "u_sam"), "user ids, in the order of the recipients"
    assert draft.not_invited == 1, "Dev from Acme has no Tilo account: counted, never invited"
    assert EXTRA_MAIL not in draft.recipients, "a person of the org who is not on the meeting is not invited"
    assert isinstance(draft.recipients, tuple) and isinstance(draft.invited, tuple)


@pytest.mark.parametrize(
    ("attendees", "recipients", "not_invited"),
    [
        ([attendee("P", "u_priya"), attendee("S", "u_sam")], (ASHA, PRIYA_MAIL, SAM_MAIL), 0),
        (
            [attendee("P", "u_priya"), attendee("A", OWNER), attendee("S", "u_sam")],
            (ASHA, PRIYA_MAIL, SAM_MAIL),
            0,
        ),
        ([attendee("P", "u_priya"), attendee("P again", "u_priya")], (ASHA, PRIYA_MAIL), 0),
        ([attendee("S", "u_sam"), attendee("X", None), attendee("Y", None)], (ASHA, SAM_MAIL), 2),
        ([], (ASHA,), 0),
    ],
)
def test_FR_MTG_09_MH_03_the_owner_is_always_first_each_user_once_and_unresolved_names_are_counted(
    attendees, recipients, not_invited
):
    draft = draft_of(meeting(attendees=attendees))

    assert draft.recipients == recipients
    assert draft.not_invited == not_invited
    assert len(draft.invited) == len(draft.recipients) and draft.invited[0] == OWNER


@pytest.mark.parametrize("attendees", [[attendee("Asha", OWNER)], [attendee("Asha", OWNER), attendee("Dev", None)]])
def test_FR_MTG_09_owner_as_the_only_attendee_still_invites_exactly_the_owner(attendees):
    draft = draft_of(meeting(attendees=attendees))

    assert draft.recipients == (ASHA,)
    assert draft.not_invited == len(attendees) - 1


def test_FR_MTG_09_the_draft_is_the_meeting_as_stored_with_the_owners_zone_and_the_pinned_exact_sentence():
    record = meeting()
    draft = draft_of(record)

    assert (draft.meeting_id, draft.org_id, draft.owner) == (MEETING_ID, "org_example", OWNER)
    assert (draft.title, draft.start, draft.end, draft.time_zone) == ("Q4 planning", T_START, T_END, IST)
    assert draft.exact == oracle_exact("Q4 planning", T_START, T_END, IST, 3, 1)
    assert local_when(T_START, T_END, IST) in draft.exact


def test_FR_MTG_09_MH_05_the_title_is_the_meeting_title_unchanged():
    for title in ("Q4 planning", "  padded title  ", 'Quarterly "board" prep', "Café ünï 計画", "Ｑ４ plan"):
        draft = draft_of(meeting(title=title))
        assert draft.title == title, "no strip, no normalisation, no cut"
        assert f'Creates "{title}" on the Tilo meeting host' in draft.exact


def test_FR_MTG_09_the_exact_sentence_counts_the_listed_people_and_the_ones_without_an_account():
    one = draft_of(meeting(attendees=default_attendees_with(1)))
    many = draft_of(meeting(attendees=default_attendees_with(3)))
    none = draft_of(meeting(attendees=default_attendees_with(0)))

    assert "1 attendee without a Tilo account is not invited. " in one.exact
    assert "3 attendees without a Tilo account are not invited. " in many.exact
    assert "without a Tilo account" not in none.exact
    assert none.exact == oracle_exact("Q4 planning", T_START, T_END, IST, 3, 0)
    assert one.exact.endswith("Guests cannot add people or see each other's addresses. An invitation cannot be unsent.")
    assert "the 3 people listed, you included" in one.exact


def default_attendees_with(unresolved: int) -> list[dict]:
    people = [attendee("Asha", OWNER), attendee("Priya", "u_priya"), attendee("Sam", "u_sam")]
    return people + [attendee(f"Guest {i}", None) for i in range(unresolved)]


def test_FR_MTG_09_the_exact_sentence_shows_start_and_end_in_the_owners_zone_not_an_attendees():
    persons = default_persons()
    persons[OWNER] = person(OWNER, ASHA, zone="America/New_York")
    persons["u_priya"] = person("u_priya", PRIYA_MAIL, zone="Asia/Tokyo")

    draft = draft_of(meeting(), persons)

    assert draft.time_zone == "America/New_York"
    assert "Tue 06 Oct 2026, 05:00 to 06:00 (America/New_York)" in draft.exact
    assert "Asia/Tokyo" not in draft.exact


def test_FR_MTG_09_content_is_the_pinned_canonical_json_and_its_hash_matches():
    record = meeting(title="Café ünï 計画")
    draft = draft_of(record)

    assert draft.content == oracle_content(record, draft.recipients)
    assert draft.content_sha256 == hashlib.sha256(draft.content).hexdigest()
    assert re.fullmatch(r"[0-9a-f]{64}", draft.content_sha256)
    draft.content.decode("ascii")  # ensure_ascii: the bytes are plain ASCII
    parsed = json.loads(draft.content)
    assert set(parsed) == {
        "v",
        "kind",
        "meeting_id",
        "owner",
        "title",
        "start",
        "end",
        "time_zone",
        "attendees",
        "conference",
        "send_updates",
        "guests_can_invite_others",
        "guests_can_modify",
        "guests_can_see_other_guests",
    }
    assert parsed["title"] == "Café ünï 計画" and parsed["kind"] == "meeting_event" and parsed["v"] == "1.0"
    assert parsed["attendees"] == list(draft.recipients)
    assert (parsed["conference"], parsed["send_updates"]) == ("hangoutsMeet", "all")
    assert not (
        parsed["guests_can_invite_others"] or parsed["guests_can_modify"] or parsed["guests_can_see_other_guests"]
    ), "guests cannot invite others, edit the event or see each other's addresses"


def test_FR_MTG_09_the_draft_holds_no_link_no_agenda_and_no_name_of_anyone_not_invited():
    record = meeting(
        attendees=[*default_attendees_with(0), attendee(f"Ask {ATTACKER} to join", None)],
    )
    record["agenda"] = [{"title": f"Loop in {ATTACKER}", "minutes": 5}]

    draft = draft_of(record)

    for text in (draft.content.decode("ascii"), draft.exact, repr(draft.recipients)):
        assert ATTACKER not in text, "an address a name or an agenda item holds is never invited or shown"
        assert "http" not in text and "meet.google.com" not in text, "the link is stored nowhere (FR-MTG-01)"
    assert ATTACKER not in draft.recipients


def test_FR_MTG_09_the_draft_is_frozen_deterministic_and_independent_of_the_inputs_it_read():
    record, persons = meeting(), default_persons()
    before = (copy.deepcopy(record), copy.deepcopy(persons))

    first = draft_of(record, persons)
    second = draft_of(record, persons)

    assert (record, persons) == before, "nothing is mutated"
    assert first == second and first.content == second.content
    with pytest.raises(dataclasses.FrozenInstanceError):
        first.title = "other"  # type: ignore[misc]
    record["title"] = "Changed later"
    record["attendees"].append(attendee("Late", "u_extra"))
    persons["u_priya"]["email"] = "changed@example.com"
    assert first == second, "an edit after the draft changes nothing in it (the pinned version)"
    assert first.recipients == (ASHA, PRIYA_MAIL, SAM_MAIL)


def test_FR_MTG_09_repr_of_a_draft_shows_no_title_address_or_sentence():
    draft = draft_of(meeting(title="Board prep for the quokka merger"))
    shown = repr(draft)

    for secret in ("quokka", ASHA, PRIYA_MAIL, SAM_MAIL, "Guests cannot", "@example", draft.content.decode("ascii")):
        assert secret not in shown, secret
    assert MEETING_ID in shown or "meeting_id" in shown


def test_FR_MTG_09_the_draft_has_no_parameter_that_can_carry_an_address_a_text_or_a_model_output():
    signature = inspect.signature(mh().draft_meeting_event)

    assert set(signature.parameters) == {"meeting", "persons", "actor", "now", "config"}
    assert all(p.kind is inspect.Parameter.KEYWORD_ONLY for p in signature.parameters.values())


# ---------------------------------------------------------------------------
# MH-01 to MH-06: the first failure raises, with the named rule


def test_FR_MTG_09_MH_01_an_actor_who_is_not_the_owner_is_refused():
    assert refusal_rule(lambda: draft_of(actor="u_priya")) == "MH-01"
    assert refusal_rule(lambda: draft_of(actor="u_extra")) == "MH-01"


@pytest.mark.parametrize("status", ["joining", "live", "ended", "minuted", "discarded", "deleted"])
def test_FR_MTG_09_MH_01_a_meeting_that_is_not_scheduled_is_refused(status):
    assert refusal_rule(lambda: draft_of(meeting(status=status))) == "MH-01"


def test_FR_MTG_09_MH_01_an_uploaded_meeting_is_refused():
    assert refusal_rule(lambda: draft_of(meeting(source="upload"))) == "MH-01"


def test_FR_MTG_09_MH_01_an_attestation_by_anyone_but_the_owner_is_refused_PE_18():
    other = {"by": "u_priya", "at": "2026-10-06T06:00:00.000Z", "notice_version": "1.0.0"}
    assert refusal_rule(lambda: draft_of(meeting(attestation=other))) == "MH-01"


@pytest.mark.parametrize(
    "changes",
    [
        {"join_url": "https://meet.google.com/abc-defg-hij"},
        {"title": "Plan at meet.google.com/abc-defg-hij"},
        {"title": "x" * 121},
        {"id": "not_a_meeting_id"},
        {"agenda": [{"title": "see zoom.us/j/123", "minutes": 5}]},
    ],
)
def test_FR_MTG_09_MH_01_a_record_that_breaks_the_meeting_contract_is_refused(changes):
    record = meeting()
    record.update(changes)
    assert schema_errors("meeting.schema.json", record) != [], "the test's premise: the record is invalid"
    assert refusal_rule(lambda: draft_of(record)) == "MH-01"


def test_FR_MTG_09_MH_02_an_unscheduled_meeting_or_one_without_an_end_is_refused():
    assert refusal_rule(lambda: draft_of(meeting(start=None))) == "MH-02"
    assert refusal_rule(lambda: draft_of(meeting(end=None))) == "MH-02"


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (T_NOW, minutes_after(T_NOW, 30)),  # starts now: not after now
        ("2026-10-06T06:59:59.999Z", T_END),  # started a millisecond ago
        ("2026-10-05T09:00:00.000Z", "2026-10-05T10:00:00.000Z"),  # yesterday
        (T_START, T_START),  # empty window
        (T_START, "2026-10-06T08:00:00.000Z"),  # ends before it starts
    ],
)
def test_FR_MTG_09_MH_02_now_must_be_before_start_and_start_before_end(start, end):
    assert refusal_rule(lambda: draft_of(meeting(start=start, end=end))) == "MH-02"


def test_FR_MTG_09_MH_02_a_meeting_one_millisecond_in_the_future_is_accepted():
    draft = draft_of(meeting(start="2026-10-06T07:00:00.001Z", end="2026-10-06T07:30:00.001Z"))
    assert draft.start == "2026-10-06T07:00:00.001Z"


def test_FR_MTG_09_MH_02_61_minutes_is_refused_and_60_minutes_passes_with_the_shipped_cap():
    assert refusal_rule(lambda: draft_of(meeting(end=minutes_after(T_START, 61)), max_duration_min=60)) == "MH-02"
    assert draft_of(meeting(end=minutes_after(T_START, 60)), max_duration_min=60).end == minutes_after(T_START, 60)
    assert draft_of(meeting(end=minutes_after(T_START, 1)), max_duration_min=60).end == minutes_after(T_START, 1)


def test_FR_MTG_09_MH_02_the_limit_comes_from_the_loaded_config_not_a_constant(tmp_path):
    path = write_personal(tmp_path, {"max_duration_min": 90})
    config = mh().load_meeting_host_config(path, registry=write_registry(tmp_path))

    def attempt(minutes):
        return mh().draft_meeting_event(
            meeting=meeting(end=minutes_after(T_START, minutes)),
            persons=default_persons(),
            actor=OWNER,
            now=T_NOW,
            config=config,
        )

    assert attempt(90).end == minutes_after(T_START, 90)
    with pytest.raises(errs().MeetingHostRefused) as raised:
        attempt(91)
    assert raised.value.rule == "MH-02"


def test_FR_MTG_09_MH_02_the_refusal_names_the_rule_and_ids_never_a_title_address_time_or_url():
    record = meeting(title="Confidential quokka merger", end=minutes_after(T_START, 120))
    with pytest.raises(errs().MeetingHostRefused) as raised:
        draft_of(record)
    text = str(raised.value) + repr(raised.value)
    assert "MH-02" in text
    for secret in ("quokka", ASHA, PRIYA_MAIL, T_START, T_END, "http", "@"):
        assert secret not in text, secret


def test_FR_MTG_09_MH_03_an_attendee_user_without_a_person_record_refuses_fail_closed():
    persons = default_persons()
    del persons["u_priya"]
    assert refusal_rule(lambda: draft_of(meeting(), persons)) == "MH-03"


def test_FR_MTG_09_MH_03_a_missing_owner_record_refuses():
    persons = default_persons()
    del persons[OWNER]
    assert refusal_rule(lambda: draft_of(meeting(), persons)) == "MH-03"


def test_FR_MTG_09_MH_03_an_attendee_of_another_org_refuses():
    persons = default_persons()
    persons["u_sam"] = person("u_sam", SAM_MAIL, org=OTHER_ORG)
    assert refusal_rule(lambda: draft_of(meeting(), persons)) == "MH-03"


@pytest.mark.parametrize(
    "broken",
    [
        {"email": "not-an-address"},
        {"time_zone": "not a zone"},
        {"org_role": "admin"},
        {"extra_field": 1},
    ],
)
def test_FR_MTG_09_MH_03_a_person_record_that_breaks_the_person_contract_refuses(broken):
    persons = default_persons()
    persons["u_priya"] = {**persons["u_priya"], **broken}
    assert schema_errors("person.schema.json", persons["u_priya"]) != []
    assert refusal_rule(lambda: draft_of(meeting(), persons)) == "MH-03"


@pytest.mark.parametrize(
    "second",
    ["priya@example.com", "Priya@Example.COM", "ＰＲＩＹＡ@example.com", "pRiYa@EXAMPLE.com"],
)
def test_FR_MTG_09_MH_03_two_users_with_one_address_NFKC_casefold_refuse(second):
    persons = default_persons()
    persons["u_sam"] = person("u_sam", second)
    persons["u_priya"] = person("u_priya", PRIYA_MAIL)
    assert refusal_rule(lambda: draft_of(meeting(), persons)) == "MH-03"


def test_FR_MTG_09_MH_03_an_attendee_who_shares_the_owners_address_refuses():
    persons = default_persons()
    persons["u_sam"] = person("u_sam", ASHA.upper())
    assert refusal_rule(lambda: draft_of(meeting(), persons)) == "MH-03"


def test_FR_MTG_09_MH_03_at_most_50_recipients_the_owner_included_the_card_and_outbox_limit():
    attendees49, persons49 = many_users(49)
    fifty = draft_of(meeting(attendees=attendees49), {**default_persons(), **persons49})
    assert len(fifty.recipients) == 50 and fifty.recipients[0] == ASHA, "owner plus 49 is 50: passes"

    attendees50, persons50 = many_users(50)
    owner_inside = [attendee("Asha", OWNER), *attendees50[:49]]
    assert len(draft_of(meeting(attendees=owner_inside), {**default_persons(), **persons50}).recipients) == 50

    assert refusal_rule(lambda: draft_of(meeting(attendees=attendees50), {**default_persons(), **persons50})) == "MH-03"


def test_FR_MTG_09_MH_04_an_owner_time_zone_zoneinfo_does_not_know_is_refused():
    persons = default_persons()
    persons[OWNER] = person(OWNER, ASHA, zone="Mars/Olympus")
    assert schema_errors("person.schema.json", persons[OWNER]) == [], "the person schema accepts the name"
    assert refusal_rule(lambda: draft_of(meeting(), persons)) == "MH-04"


def test_FR_MTG_09_MH_04_only_the_owners_zone_counts_an_attendee_with_an_odd_zone_is_still_invited():
    persons = default_persons()
    persons["u_sam"] = person("u_sam", SAM_MAIL, zone="Mars/Olympus")
    assert draft_of(meeting(), persons).recipients == (ASHA, PRIYA_MAIL, SAM_MAIL)


def test_FR_MTG_09_MH_06_an_exact_sentence_over_500_characters_is_refused_never_cut():
    zone = "America/Argentina/ComodRivadavia"
    persons = default_persons()
    persons[OWNER] = person(OWNER, ASHA, zone=zone)
    attendees = [attendee("Asha", OWNER), *(attendee(f"Guest {i}", None) for i in range(49))]
    title = "T" * 120
    assert len(oracle_exact(title, T_START, T_END, zone, 1, 49)) > EXACT_MAX, "the test's premise"

    assert refusal_rule(lambda: draft_of(meeting(title=title, attendees=attendees), persons)) == "MH-06"


def test_FR_MTG_09_MH_06_exactly_500_characters_passes_and_501_is_refused():
    zone = "America/Argentina/ComodRivadavia"
    persons = default_persons()
    persons[OWNER] = person(OWNER, ASHA, zone=zone)
    attendees = [attendee("Asha", OWNER), *(attendee(f"Guest {i}", None) for i in range(49))]
    room = EXACT_MAX - len(oracle_exact("", T_START, T_END, zone, 1, 49))
    assert 1 <= room <= 119, "the test's premise: a title of this length exists"

    exact = draft_of(meeting(title="T" * room, attendees=attendees), persons).exact
    assert len(exact) == EXACT_MAX == len(oracle_exact("T" * room, T_START, T_END, zone, 1, 49))
    assert exact == oracle_exact("T" * room, T_START, T_END, zone, 1, 49), "whole, not cut"
    assert refusal_rule(lambda: draft_of(meeting(title="T" * (room + 1), attendees=attendees), persons)) == "MH-06"


@pytest.mark.parametrize(
    ("first", "second", "build"),
    [
        ("MH-01", "MH-02", lambda: draft_of(meeting(source="upload", start=None))),
        ("MH-01", "MH-03", lambda: draft_of(meeting(status="live"), _without("u_priya"))),
        ("MH-02", "MH-03", lambda: draft_of(meeting(end=minutes_after(T_START, 120)), _without("u_priya"))),
        ("MH-03", "MH-04", lambda: draft_of(meeting(), _without("u_priya", zone="Mars/Olympus"))),
        ("MH-02", "MH-04", lambda: draft_of(meeting(end=minutes_after(T_START, 120)), _without(zone="Mars/Olympus"))),
    ],
)
def test_FR_MTG_09_the_checks_run_in_order_and_the_first_failure_raises(first, second, build):
    assert refusal_rule(build) == first, f"{first} comes before {second}"


def _without(*users: str, zone: str | None = None) -> dict:
    persons = default_persons()
    for user in users:
        del persons[user]
    if zone is not None:
        persons[OWNER] = person(OWNER, ASHA, zone=zone)
    return persons


# ---------------------------------------------------------------------------
# host_gate: what the card builder, approval.requested and the outbox entry copy (MH-07)


def _stored(draft, **kw):
    return DraftArtifacts().put_draft(draft.content, **kw)


def test_FR_MTG_09_host_gate_returns_exactly_the_pinned_values():
    draft = draft_of()
    stored = _stored(draft)

    gate = mh().host_gate(draft, stored, host_decl())

    assert gate == {
        "action_type": "create_meeting_event",
        "connector": "meeting_host",
        "risk_tier": "T3",
        "irreversible": True,
        "modifiers": ["new_recipients"],
        "recipients": [ASHA, PRIYA_MAIL, SAM_MAIL],
        "attachments": [],
        "item": {"artifact_id": stored["artifact"]["artifact_id"], "version": stored["artifact"]["version"]},
        "destination": "primary",
        "exact": draft.exact,
        "undo_window_s": 0,
    }


def test_FR_MTG_09_host_gate_item_is_the_stored_artifact_ref_without_a_label():
    draft = draft_of()
    stored = _stored(draft, label="Meeting invitation")
    assert "label" in stored["artifact"]

    gate = mh().host_gate(draft, stored, host_decl())

    assert "label" not in gate["item"]
    assert gate["item"] == {k: stored["artifact"][k] for k in ("artifact_id", "version")}
    assert "label" in stored["artifact"], "the store's record is not edited"


def test_FR_MTG_09_host_gate_modifiers_equal_what_the_policy_engine_assesses():
    draft = draft_of()
    gate = mh().host_gate(draft, _stored(draft), host_decl())
    assessed = load_risk_table().assess(
        ACTION_TYPE, SideEffectFacts(recipients=draft.recipients, known_recipients=(), safety_flags=False)
    )
    assert tuple(gate["modifiers"]) == assessed.modifiers == ("new_recipients",)
    assert gate["risk_tier"] == assessed.tier == "T3"


@pytest.mark.parametrize("screening", ["flagged", "unscreened"])
def test_FR_MTG_09_PE_21_a_draft_that_is_not_clean_still_gates_with_safety_flag_never_refused(screening):
    draft = draft_of()
    stored = _stored(draft, screening=screening)

    gate = mh().host_gate(draft, stored, host_decl())

    assert gate["modifiers"] == ["new_recipients", "safety_flag"]
    assessed = load_risk_table().assess(
        ACTION_TYPE, SideEffectFacts(recipients=draft.recipients, known_recipients=(), safety_flags=True)
    )
    assert tuple(gate["modifiers"]) == assessed.modifiers and gate["risk_tier"] == "T3"


def test_FR_MTG_09_the_gate_values_fit_the_gate_card_and_the_card_shows_what_the_entry_will_send():
    draft = draft_of()
    gate = mh().host_gate(draft, _stored(draft), host_decl())

    card = build_card(gate)

    assert schema_errors("card.schema.json", card) == []
    assert card["gate"]["recipients"] == list(draft.recipients)
    assert card["gate"]["action"]["exact"] == draft.exact and len(draft.exact) <= EXACT_MAX
    assert (card["gate"]["irreversible"], card["gate"]["risk_tier"]) == (True, "T3")


def _declaration_variants():
    def change(**kw):
        d = host_decl()
        for key, value in kw.items():
            if key.startswith("action_"):
                d["actions"][0][key.removeprefix("action_")] = value
            else:
                d[key] = value
        return d

    gmail = host_decl()
    gmail["id"] = "gmail"
    return {
        "another connector": gmail,
        "tier T2": change(action_risk_tier="T2"),
        "reversible": change(action_irreversible=False),
        "capability write": change(action_capability="write"),
        "a wider scope": change(
            scopes={"send": ["https://www.googleapis.com/auth/calendar.events"]},
        ),
        "another action": change(action_id="create_event"),
    }


@pytest.mark.parametrize("name", sorted(_declaration_variants()))
def test_FR_MTG_09_MH_07_host_gate_refuses_a_declaration_that_is_not_the_meeting_host_one(name):
    draft = draft_of()
    assert refusal_rule(lambda: mh().host_gate(draft, _stored(draft), _declaration_variants()[name])) == "MH-07"


def test_FR_MTG_09_MH_07_host_gate_refuses_a_store_record_that_is_not_the_draft_as_stored():
    draft = draft_of()
    decl = host_decl()
    redacted = _stored(draft, redacted_to=draft.content.replace(b"Q4", b"[X]"))
    markdown = {**_stored(draft), "media_type": "text/markdown"}
    uploaded = _stored(draft, origin_kind="upload")

    assert refusal_rule(lambda: mh().host_gate(draft, redacted, decl)) == "MH-07", "the store's redactor changed it"
    assert refusal_rule(lambda: mh().host_gate(draft, markdown, decl)) == "MH-07"
    assert refusal_rule(lambda: mh().host_gate(draft, uploaded, decl)) == "MH-07", "only a unit's own output"


def test_FR_MTG_09_MH_07_host_gate_refuses_when_the_hash_of_the_stored_bytes_differs():
    draft = draft_of()
    stored = _stored(draft)
    stored["content_sha256"] = hashlib.sha256(b"something else").hexdigest()
    assert refusal_rule(lambda: mh().host_gate(draft, stored, host_decl())) == "MH-07"


# ---------------------------------------------------------------------------
# Properties (invariants over generated meetings)


def _pool() -> tuple[dict[str, dict], list[str]]:
    persons = {OWNER: person(OWNER, ASHA, name="Asha Rao", role="owner")}
    users = []
    for i in range(1, 21):
        user = f"u_q{i:02d}"
        users.append(user)
        persons[user] = person(user, f"q{i:02d}@example.com")
    return persons, users


@PROPERTY
@given(picks=st.lists(st.one_of(st.none(), st.integers(0, 20)), max_size=30))
def test_FR_MTG_09_property_recipients_are_the_owner_first_each_user_once_in_attendee_order(picks):
    persons, users = _pool()
    attendees, expected_users, unresolved = [], [OWNER], 0
    for i, pick in enumerate(picks):
        if pick is None:
            attendees.append(attendee(f"Guest {i}", None))
            unresolved += 1
            continue
        user = OWNER if pick == 20 else users[pick]
        attendees.append(attendee(f"Name {i}", user))
        if user not in expected_users:
            expected_users.append(user)

    record = meeting(attendees=attendees)

    draft = draft_of(record, persons)

    assert list(draft.invited) == expected_users
    assert draft.not_invited == unresolved
    assert draft.recipients[0] == ASHA and len(set(draft.recipients)) == len(draft.recipients) <= 50
    assert draft.recipients == tuple(persons[u]["email"] for u in draft.invited)
    assert draft.content == oracle_content(record, draft.recipients)


@PROPERTY
@given(minutes=st.integers(1, 200), cap=st.integers(1, 120))
def test_FR_MTG_09_property_the_duration_cap_is_never_exceeded(minutes, cap):
    record = meeting(end=minutes_after(T_START, minutes))
    if minutes <= cap:
        assert draft_of(record, max_duration_min=cap).end == record["scheduled"]["end"]
    else:
        assert refusal_rule(lambda: draft_of(record, max_duration_min=cap)) == "MH-02"


@PROPERTY
@given(
    title_len=st.integers(1, 120),
    unresolved=st.integers(0, 49),
    zone=st.sampled_from(["UTC", IST, "America/New_York", "America/Argentina/ComodRivadavia"]),
)
def test_FR_MTG_09_property_exact_is_whole_and_at_most_500_or_the_draft_is_refused(title_len, unresolved, zone):
    persons = default_persons()
    persons[OWNER] = person(OWNER, ASHA, zone=zone)
    attendees = [attendee("Asha", OWNER), *(attendee(f"Guest {i}", None) for i in range(unresolved))]
    title = "T" * title_len
    expected = oracle_exact(title, T_START, T_END, zone, 1, unresolved)

    if len(expected) <= EXACT_MAX:
        assert draft_of(meeting(title=title, attendees=attendees), persons).exact == expected
    else:
        assert refusal_rule(lambda: draft_of(meeting(title=title, attendees=attendees), persons)) == "MH-06"


def test_FR_MTG_09_the_draft_function_is_registered_for_this_connector_and_action_only():
    assert (mh().CONNECTOR_ID, mh().ACTION_TYPE) == (CONNECTOR_ID, ACTION_TYPE)
    assert host_config(60).max_duration_min == 60
