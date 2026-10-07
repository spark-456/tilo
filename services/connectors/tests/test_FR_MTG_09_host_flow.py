"""FR-MTG-09 acceptance (a), (b), (c) and the adapter rules MH-10 to MH-14: the bot-hosted meeting through the
outbox, on a fake Google Calendar. API_FR_MTG_09.md "Ordered flow", "Acceptance tests: the exact assertions",
"`tilo_connectors.adapters.meeting_host`"; ADR-0024 decisions 3 and 4; BQ-MTG09-1, BQ-MTG09-8, BQ-MTG09-12.

Every side effect enters through `Outbox.enqueue` + `dispatch_due` (SEC-03); direct calls are refused. Nothing
here opens a socket, calls a model or reads LIVE. Tests that need `tilo_connectors.meeting_host` or
`tilo_connectors.adapters.meeting_host` fail today with ModuleNotFoundError; the `premise` tests pass today: they
prove the hand-built entries are accepted by the unchanged outbox, so it is the adapter that refuses them.
"""

from __future__ import annotations

import copy
import json
import logging
import re

import pytest
from _connectors_lib import ManualClock, add_seconds
from _meeting_host_lib import (
    ACTION_TYPE,
    APPROVER,
    ASHA,
    ATTACKER,
    CALENDAR_EVENTS_OWNED,
    CONNECTOR_ID,
    EVENTS_URL,
    OWNER,
    PRIYA_MAIL,
    SAM_MAIL,
    T_NOW,
    T_UPDATED,
    WORLD,
    ByteReceiptStore,
    FlakyReceipts,
    build_case,
    default_persons,
    enqueue,
    errs,
    everything_text,
    literal_gate,
    make_host_env,
    many_users,
    marker_of,
    meeting,
    mha,
    no_network_and_no_live,  # noqa: F401 - autouse guard
    oracle_insert_body,
    oracle_params,
    planted_needles,
)
from _oauth_lib import schema_errors
from tilo_connectors import InMemoryOutboxStore, Outbox, OutboxRefused

SOON_START = "2026-10-06T07:10:00.000Z"  # ten minutes after T_NOW: the access token is still valid at the start
SOON_END = "2026-10-06T07:40:00.000Z"


def soon() -> dict:
    return meeting(start=SOON_START, end=SOON_END)


def states(entries: list[dict]) -> list[str]:
    return [e["state"] for e in entries]


def nothing_sent(host) -> None:
    assert host.cal.requests == [], "Google saw no request"
    assert host.cal.invitations() == [] and host.transfers() == []


# ---------------------------------------------------------------------------
# (a) nothing before approval


def test_FR_MTG_09_a_steps_1_to_5_write_no_outbox_entry_make_no_request_and_emit_nothing():
    host = make_host_env()

    flow = host.prepare()

    assert host.outbox.get(flow.entry["id"]) is None
    assert host.store.all_entries() == []
    assert host.outbox.dispatch_due() == []
    nothing_sent(host)
    assert host.flow_parts() == [], "no part: the draft, the stored artifact and the card are not events"
    assert host.spy.asked == [], "the broker was not asked for a token"
    assert host.stored_receipts() == [] and host.artifacts.reads == []


@pytest.mark.parametrize("option", ["hold", "edit"])
def test_FR_MTG_09_a_a_hold_or_edit_answer_enqueues_nothing_and_Google_hears_nothing(option):
    host = make_host_env()
    flow = host.prepare()

    with pytest.raises(OutboxRefused):
        enqueue(host.outbox, flow.case, option=option)

    assert host.outbox.get(flow.entry["id"]) is None
    assert host.outbox.dispatch_due() == []
    nothing_sent(host)


def test_FR_MTG_09_a_an_entry_with_no_approval_at_all_is_refused():
    host = make_host_env()
    flow = host.prepare()

    with pytest.raises(OutboxRefused):
        enqueue(host.outbox, flow.case, authorised_by=None)

    assert host.store.all_entries() == []
    assert host.outbox.dispatch_due() == []
    nothing_sent(host)


def test_FR_MTG_09_a_an_approval_by_another_person_does_not_open_the_gate():
    host = make_host_env()
    flow = host.prepare()
    resolved = copy.deepcopy(flow.case["authorised_by"])
    resolved["authz"] = {"by": "person", "ref": "u_priya", "at": T_NOW}

    with pytest.raises(OutboxRefused):
        enqueue(host.outbox, flow.case, authorised_by=resolved)

    nothing_sent(host)


@pytest.mark.parametrize("channel", ["email", "whatsapp", "slack", "sms"])
def test_FR_MTG_09_a_an_approval_on_any_channel_but_a_signed_in_web_session_opens_nothing(channel):
    host = make_host_env()
    flow = host.prepare(channel=channel)

    with pytest.raises(OutboxRefused):
        enqueue(host.outbox, flow.case)

    assert host.store.all_entries() == [], "no entry"
    assert host.outbox.dispatch_due() == []
    nothing_sent(host)


@pytest.mark.parametrize("channel", ["web", "mobile_web"])
def test_FR_MTG_09_a_an_approval_in_a_signed_in_web_or_mobile_web_session_opens_the_gate(channel):
    host = make_host_env()
    flow = host.prepare(channel=channel)

    assert states(host.settle(flow)) == ["sent"]
    assert len(host.cal.posts()) == 1


def test_FR_MTG_09_a_an_approved_gate_makes_one_insert_one_event_one_invitation_per_recipient_one_receipt():
    host = make_host_env()
    flow = host.prepare()

    settled = host.settle(flow)

    assert states(settled) == ["sent"] and settled[0]["id"] == flow.entry["id"]
    assert len(host.cal.posts()) == 1, "exactly one insert"
    assert len(host.cal.created()) == 1, "exactly one event"
    invited = [address for _event, address in host.cal.invitations()]
    assert sorted(invited) == sorted(flow.draft.recipients) == sorted([ASHA, PRIYA_MAIL, SAM_MAIL])
    assert len(invited) == len(set(invited)), "one invitation per recipient"
    assert len(host.stored_receipts()) == 1, "one receipt"
    assert host.cal.gets() == [], "the plain path reads nothing back"


def test_FR_MTG_09_a_the_one_data_transfer_carries_the_approvals_authz_and_the_gates_item():
    host = make_host_env()
    flow = host.prepare()

    host.settle(flow)

    (transfer,) = host.transfers()
    assert transfer["authz"] == flow.case["authorised_by"]["authz"] == flow.entry["authz"]
    assert transfer["data"]["artifact"] == flow.gate["item"], "data.artifact equals gate.action.item"
    assert transfer["data"]["direction"] == "out"
    assert (transfer["data"]["connector"], transfer["data"]["action_type"]) == (CONNECTOR_ID, ACTION_TYPE)
    assert transfer["data"]["outbox_id"] == flow.entry["id"] and transfer["data"]["risk_tier"] == "T3"
    assert schema_errors("events/data/data.transfer.schema.json", transfer["data"]) == []
    assert "recipients" not in transfer["data"], "no address in the event"


def test_FR_MTG_09_a_the_adapter_returns_the_receipt_ref_and_the_conference_status_and_emits_nothing_itself():
    host = make_host_env()
    flow = host.prepare()

    host.settle(flow)

    (result,) = host.recorder.results
    receipt = host.stored_receipts()[0]
    assert result == {"receipt": host.receipts.put(receipt), "conference": "success"}
    assert [p["type"] for p in host.flow_parts()] == ["data.transfer"], "only the outbox emits the one transfer"


def test_FR_MTG_09_a_a_sent_entry_is_never_sent_again():
    host = make_host_env()
    flow = host.prepare()
    host.settle(flow)

    assert host.outbox.dispatch_due() == [] and host.outbox.dispatch_due() == []

    assert len(host.cal.posts()) == 1 and len(host.cal.invitations()) == 3


def test_FR_MTG_09_a_execute_side_effect_without_a_grant_raises_MissingGrant_and_Google_sees_nothing():
    from tilo_connectors.outbox import Grant

    host = make_host_env()
    flow = host.prepare()
    host.outbox.enqueue(copy.deepcopy(flow.entry), _evidence(flow))
    entry = host.store.get(flow.entry["id"])

    for grant in (None, Grant(world_id=entry["world_id"], idempotency_key=entry["idempotency_key"]), "granted"):
        with pytest.raises(errs().MissingGrant):
            host.adapter.execute_side_effect(entry, grant)

    nothing_sent(host)
    assert host.spy.asked == [] and host.artifacts.reads == [], "refused before anything is read (SEC-03)"


def _evidence(flow):
    from _connectors_lib import evidence_from_case

    return evidence_from_case(copy.deepcopy(flow.case))


def test_FR_MTG_09_a_SEC_03_the_adapters_side_effect_method_is_still_the_one_the_registry_names():
    from tilo_connectors.side_effects import SIDE_EFFECT_METHOD_NAMES

    assert SIDE_EFFECT_METHOD_NAMES == frozenset({"send_reply", "execute_side_effect"})
    assert callable(getattr(mha().MeetingHostAdapter, "execute_side_effect", None))
    public = {n for n in dir(mha().MeetingHostAdapter) if not n.startswith("_")}
    assert not ({"create_meeting_event", "insert_event", "invite", "send"} & public), "no other way in"


# ---------------------------------------------------------------------------
# (b) the invitation is exactly what the card showed


def test_FR_MTG_09_b_the_insert_has_the_pinned_params_and_body_built_from_the_pinned_draft():
    host = make_host_env()
    flow = host.prepare()
    host.settle(flow)

    (post,) = host.cal.posts()
    entry = host.store.get(flow.entry["id"])
    draft = json.loads(flow.draft.content)

    assert post.url == EVENTS_URL
    assert (
        post.params
        == oracle_params()
        == {
            "conferenceDataVersion": 1,
            "sendUpdates": "all",
            "fields": "id,status,conferenceData(createRequest(status(statusCode)))",
        }
    )
    assert post.json == oracle_insert_body(entry, draft), "no description, location, attachment, reminder or colour"
    assert post.json["id"] == marker_of(entry) and re.fullmatch(r"[0-9a-f]{32}", post.json["id"])
    assert post.json["conferenceData"]["createRequest"]["conferenceSolutionKey"] == {"type": "hangoutsMeet"}
    assert (post.json["summary"], post.json["start"]["dateTime"], post.json["end"]["dateTime"]) == (
        draft["title"],
        draft["start"],
        draft["end"],
    )
    assert post.json["guestsCanInviteOthers"] is False
    assert post.json["guestsCanModify"] is False
    assert post.json["guestsCanSeeOtherGuests"] is False
    assert "sendUpdates" not in post.json, "a request parameter, not a body field"


def test_FR_MTG_09_b_the_attendees_equal_the_card_the_entry_and_the_draft_in_the_same_order():
    host = make_host_env()
    flow = host.prepare()
    host.settle(flow)

    (post,) = host.cal.posts()
    entry = host.store.get(flow.entry["id"])
    draft = json.loads(flow.draft.content)

    emails = [a["email"] for a in post.json["attendees"]]
    assert emails == flow.card["gate"]["recipients"] == entry["recipients"] == draft["attendees"]
    assert all(set(a) == {"email"} for a in post.json["attendees"]), "an address and nothing else about a guest"


def test_FR_MTG_09_b_one_item_ref_runs_through_the_entry_card_approval_transfer_and_receipt():
    host = make_host_env()
    flow = host.prepare()
    host.settle(flow)

    entry = host.store.get(flow.entry["id"])
    (transfer,) = host.transfers()
    receipt = host.stored_receipts()[0]

    assert (
        entry["item"]
        == flow.card["gate"]["action"]["item"]
        == flow.case["reserved_by"]["data"]["item"]
        == transfer["data"]["artifact"]
        == dict(receipt.draft)
        == {"artifact_id": flow.stored["artifact"]["artifact_id"], "version": flow.stored["artifact"]["version"]}
    )
    assert entry["destination"] == flow.card["gate"]["action"]["destination"] == "primary"


def test_FR_MTG_09_b_the_request_carries_the_token_of_the_owners_meeting_host_grant_and_asks_for_one_scope():
    host = make_host_env(connect_gmail=True)
    gmail_token = host.broker.access_token_for_adapter(
        OWNER, "gmail", required_scopes=["https://www.googleapis.com/auth/gmail.readonly"]
    )
    flow = host.prepare()
    host.settle(flow)

    (post,) = host.cal.posts()

    assert post.token == host.host_token() != gmail_token, "the second Google account's token, not the person's"
    assert host.spy.asked == [(OWNER, "meeting_host", (CALENDAR_EVENTS_OWNED,), False)]


def test_FR_MTG_09_b_the_event_id_is_the_outbox_marker_and_a_retry_of_the_entry_asks_for_the_same_id():
    from tilo_connectors.adapters import side_effect_marker

    host = make_host_env()
    flow = host.prepare()
    host.cal.lose_answer_after_create()
    enqueue(host.outbox, flow.case)
    host.outbox.dispatch_due()
    host.outbox.dispatch_due()

    entry = host.store.get(flow.entry["id"])
    ids = {post.json["id"] for post in host.cal.posts()}

    assert ids == {marker_of(entry)} == {side_effect_marker(entry)}
    assert host.stored_receipts()[0].event_ref == marker_of(entry)
    assert list(host.cal.events) == [marker_of(entry)]


def test_FR_MTG_09_b_the_receipt_holds_ids_only_and_the_conference_status():
    host = make_host_env()
    flow = host.prepare()
    host.settle(flow)

    receipt = host.stored_receipts()[0]
    entry = host.store.get(flow.entry["id"])

    assert (receipt.world_id, receipt.outbox_id, receipt.meeting_id, receipt.owner) == (
        WORLD,
        entry["id"],
        flow.draft.meeting_id,
        OWNER,
    )
    assert re.fullmatch(r"[0-9a-f]{32}", receipt.event_ref) and receipt.conference == "success"
    assert "label" not in receipt.draft


def test_FR_MTG_09_b_the_receipt_bytes_are_the_pinned_canonical_json_with_no_link_address_title_or_time():
    host = make_host_env(receipts=ByteReceiptStore())
    flow = host.prepare()
    host.settle(flow)

    (data,) = host.receipts.all_bytes()
    parsed = json.loads(data)

    assert set(parsed) == {
        "v",
        "kind",
        "connector",
        "calendar",
        "event_ref",
        "meeting_id",
        "draft",
        "outbox_id",
        "conference",
    }
    assert (parsed["kind"], parsed["connector"], parsed["calendar"]) == (
        "meeting_event_receipt",
        CONNECTOR_ID,
        "primary",
    )
    text = data.decode("ascii")
    for hidden in ("Q4 planning", ASHA, PRIYA_MAIL, "2026-10-06", "http", "meet.google.com"):
        assert hidden not in text, hidden


# ---------------------------------------------------------------------------
# (c) the link is stored nowhere


def test_FR_MTG_09_c_a_planted_link_and_html_link_occur_in_no_part_log_error_receipt_row_card_or_artifact(caplog):
    caplog.set_level(logging.DEBUG)
    host = make_host_env(receipts=ByteReceiptStore())
    flow = host.prepare()

    host.cal.fail_next(500)  # a failure first: its body echoes the planted link too
    enqueue(host.outbox, flow.case)
    host.outbox.dispatch_due()
    host.cal.lose_answer_after_create()  # then a lost answer, then the 409 path reads the event back
    host.outbox.dispatch_due()
    host.outbox.dispatch_due()

    entry = host.store.get(flow.entry["id"])
    assert entry["state"] == "sent" and len(host.cal.gets()) == 1, "the GET path ran: its answer is hostile too"
    text = everything_text(host, caplog, json.dumps(flow.card), repr(flow.draft), repr(host.stored_receipts()))
    for needle in planted_needles(host):
        assert needle not in text, "the Meet link (or the htmlLink) is stored nowhere"
    assert host.cal.plant.link not in host.recorder.error_text()


def test_FR_MTG_09_c_attendee_addresses_occur_only_in_the_entry_recipients_the_card_and_the_draft(caplog):
    caplog.set_level(logging.DEBUG)
    host = make_host_env(receipts=ByteReceiptStore())
    flow = host.prepare()
    host.cal.fail_next(500)
    enqueue(host.outbox, flow.case)
    host.outbox.dispatch_due()
    host.outbox.dispatch_due()
    card_without_recipients = {**flow.card, "gate": {**flow.card["gate"], "recipients": []}}

    text = everything_text(
        host,
        caplog,
        json.dumps(card_without_recipients),
        with_drafts=False,
        with_recipients=False,
    )

    for address in (ASHA, PRIYA_MAIL, SAM_MAIL, host.cal.plant.organizer):
        assert address not in text, f"{address} is in a part, log, error, receipt or row it should not be in"
    entry = host.store.get(flow.entry["id"])
    assert entry["recipients"] == list(flow.draft.recipients), "the entry is where an address may be"
    assert all(a.encode() in flow.draft.content for a in flow.draft.recipients), "and so is the draft"


def test_FR_MTG_09_c_a_hostile_answer_on_every_status_leaks_nothing_either(caplog):
    caplog.set_level(logging.DEBUG)
    host = make_host_env(receipts=ByteReceiptStore())
    for status in (400, 403, 404, 409, 429, 500, 503):
        flow = host.prepare()
        host.cal.fail_next(status, headers={"retry-after": "1"} if status == 429 else None)
        enqueue(host.outbox, flow.case)
        host.outbox.dispatch_due()

    text = everything_text(host, caplog, json.dumps(host.alerts))
    for needle in planted_needles(host):
        assert needle not in text


# ---------------------------------------------------------------------------
# MH-10 the entry, MH-11 the draft: hand-built entries the unchanged outbox accepts and the adapter refuses


def _set_item_none(case):
    case["entry"]["item"] = None
    case["reserved_by"]["data"]["item"] = None


def _set_action_type(case):
    case["entry"]["action_type"] = "send_email"
    case["reserved_by"]["data"]["action_type"] = "send_email"


def _set_tier_t2(case):
    for holder in (case["entry"], case["reserved_by"]["data"]):
        holder["risk_tier"] = "T2"
    case["entry"]["modifiers"] = []


def _set_undo_window(case):
    case["entry"]["undo_window_s"] = 30
    case["entry"]["state"] = "scheduled"
    case["entry"]["scheduled_at"] = add_seconds(case["entry"]["created_at"], 30)


def _set_approver(case):
    stamp = {"by": OWNER, "at": T_UPDATED}
    case["reserved_by"]["data"]["approver"] = {"user": APPROVER, "assigned_by": stamp}
    authz = {"by": "person", "ref": APPROVER, "at": T_NOW}
    case["entry"]["authz"] = authz
    case["authorised_by"]["authz"] = copy.deepcopy(authz)


MUTATIONS = {
    "another action type": _set_action_type,
    "tier T2": _set_tier_t2,
    "no new_recipients modifier": lambda c: c["entry"].update(modifiers=[]),
    "an attachment": lambda c: c["entry"].update(
        attachments=[{"artifact_id": "art_extra", "version": 1}], modifiers=["new_recipients", "attachments"]
    ),
    "another destination": lambda c: c["entry"].update(destination="other_calendar"),
    "no destination": lambda c: c["entry"].update(destination=None),
    "no item": _set_item_none,
    "an undo window": _set_undo_window,
    "no recipients": lambda c: c["entry"].update(recipients=[]),
    "an Approver, not the owner, approved": _set_approver,
}


def _mutated_case(base: dict, name: str) -> dict:
    case = copy.deepcopy(base)
    MUTATIONS[name](case)
    return case


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_FR_MTG_09_MH_10_premise_the_unchanged_outbox_accepts_the_hand_built_entry(name):
    case = _mutated_case(build_case(None, literal_gate()), name)
    outbox = Outbox(InMemoryOutboxStore(), {}, emit=[].append, clock=ManualClock(T_NOW))

    stored = enqueue(outbox, case)

    assert stored["id"] == case["entry"]["id"], "so a refusal below is the adapter's"
    assert schema_errors("outbox.schema.json", case["entry"]) == []


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_FR_MTG_09_MH_10_MH_11_the_adapter_refuses_an_entry_that_is_not_what_the_owner_approved(name):
    host = make_host_env()
    flow = host.prepare()
    enqueue(host.outbox, _mutated_case(flow.case, name))
    host.clock.advance(31)  # past the undo window of the one case that has one

    settled = host.outbox.dispatch_due()

    assert states(settled) == ["failed"], "a final refusal: the entry ends failed"
    assert host.cal.requests == [] and host.spy.asked == [], "no request, no token asked for"
    assert host.transfers() == [] and host.stored_receipts() == [], "no data.transfer, no receipt"
    (error,) = host.recorder.errors
    assert isinstance(error, errs().SideEffectRefused) and not isinstance(error, errs().PossiblySent)
    assert host.alerts == [], "nothing may have been sent, so nobody is alerted"
    assert host.outbox.dispatch_due() == [] and host.cal.requests == [], "and it is never tried again"


def test_FR_MTG_09_MH_11_the_world_owner_must_be_the_drafts_owner_and_the_approver():
    host = make_host_env()
    flow = host.prepare()
    host.owner_for_world = lambda world_id: "u_priya"
    enqueue(host.outbox, flow.case)

    assert states(host.outbox.dispatch_due()) == ["failed"]
    nothing_sent(host)
    assert host.spy.asked == []


def test_FR_MTG_09_MH_11_a_draft_made_for_another_owner_is_refused_even_with_a_valid_hash():
    host = make_host_env()
    flow = host.prepare()
    forged = json.loads(flow.draft.content)
    forged["owner"] = "u_priya"
    ref = _store_json(host, forged)
    case = _case_pointing_at(flow, ref)
    enqueue(host.outbox, case)

    assert states(host.outbox.dispatch_due()) == ["failed"]
    nothing_sent(host)


def test_FR_MTG_09_MH_11_an_artifact_that_is_not_a_meeting_event_draft_is_refused():
    host = make_host_env()
    flow = host.prepare()
    other = json.loads(flow.draft.content)
    other["kind"] = "email"
    ref = _store_json(host, other)
    enqueue(host.outbox, _case_pointing_at(flow, ref))

    assert states(host.outbox.dispatch_due()) == ["failed"]
    nothing_sent(host)


def _store_json(host, value: dict) -> dict:
    from _meeting_host_lib import canonical

    stored = host.artifacts.put_draft(canonical(value))
    return {"artifact_id": stored["artifact"]["artifact_id"], "version": stored["artifact"]["version"]}


def _case_pointing_at(flow, ref: dict) -> dict:
    case = copy.deepcopy(flow.case)
    case["entry"]["item"] = copy.deepcopy(ref)
    case["reserved_by"]["data"]["item"] = copy.deepcopy(ref)
    return case


# ---------------------------------------------------------------------------
# MH-12 an invitation never goes out for a meeting that has started


def test_FR_MTG_09_MH_12_an_entry_still_unsent_at_the_start_time_is_refused_one_millisecond_before_it_sends():
    host = make_host_env()
    flow = host.prepare(soon())
    enqueue(host.outbox, flow.case)
    host.clock.set("2026-10-06T07:09:59.999Z")

    assert states(host.outbox.dispatch_due()) == ["sent"], "one millisecond before the start"
    assert len(host.cal.posts()) == 1


@pytest.mark.parametrize("at", [SOON_START, "2026-10-06T07:10:00.001Z", SOON_END, "2026-10-06T09:00:00.000Z"])
def test_FR_MTG_09_MH_12_at_or_after_the_start_the_entry_fails_with_no_request(at):
    host = make_host_env()
    flow = host.prepare(soon())
    enqueue(host.outbox, flow.case)
    host.clock.set(at)

    assert states(host.outbox.dispatch_due()) == ["failed"]
    nothing_sent(host)
    assert host.spy.asked == [], "refused before a token is asked for"
    assert isinstance(host.recorder.errors[0], errs().SideEffectRefused)


# ---------------------------------------------------------------------------
# The request failures (step 5 and 6): waits for a person, retries, final


def _attempts(host, flow) -> int:
    return host.store.retry_state(flow.entry["id"])["attempts"]


def test_FR_MTG_09_NotConnected_makes_no_request_spends_no_attempt_and_keeps_the_entry_due():
    host = make_host_env(connect_host=False)
    flow = host.prepare()
    enqueue(host.outbox, flow.case)

    assert host.outbox.dispatch_due() == []

    assert host.cal.requests == [], "no request when nobody connected the host account"
    assert _attempts(host, flow) == 0, "waiting for a person spends no attempt"
    assert host.store.get(flow.entry["id"])["state"] in ("queued", "sending")
    assert isinstance(host.recorder.errors[0], not_connected_type())
    host.env.connect(OWNER, CONNECTOR_ID, [CALENDAR_EVENTS_OWNED])  # the Owner connects later
    assert states(host.outbox.dispatch_due()) == ["sent"]
    assert len(host.cal.posts()) == 1


def not_connected_type():
    from tilo_connectors.tokens import NotConnected

    return NotConnected


def test_FR_MTG_09_InsufficientScope_makes_no_request_and_spends_no_attempt():
    from tilo_connectors.tokens import InsufficientScope

    host = make_host_env(connect_host=False)
    host.env.connect(OWNER, CONNECTOR_ID, ["https://www.googleapis.com/auth/calendar.readonly"])
    flow = host.prepare()
    enqueue(host.outbox, flow.case)

    assert host.outbox.dispatch_due() == []

    assert host.cal.requests == [] and _attempts(host, flow) == 0
    assert isinstance(host.recorder.errors[0], InsufficientScope)


def test_FR_MTG_09_ConnectionExpired_makes_no_request_and_spends_no_attempt():
    from tilo_connectors.tokens import ConnectionExpired

    host = make_host_env()
    flow = host.prepare(meeting(start="2026-10-06T12:00:00.000Z", end="2026-10-06T12:30:00.000Z"))
    enqueue(host.outbox, flow.case)
    host.clock.advance(2 * 3600)  # the access token ran out; Google will no longer refresh it
    host.env.google.refresh_mode = "invalid_grant"

    assert host.outbox.dispatch_due() == []

    assert host.cal.requests == [] and _attempts(host, flow) == 0
    assert isinstance(host.recorder.errors[0], ConnectionExpired)


def test_FR_MTG_09_a_401_gets_one_forced_refresh_and_still_one_event():
    host = make_host_env()
    flow = host.prepare()
    host.cal.fail_next(401)

    assert states(host.settle(flow)) == ["sent"]

    assert [a[3] for a in host.spy.asked] == [False, True], "the second ask is the one forced refresh"
    assert len(host.cal.created()) == 1 and len(host.cal.invitations()) == 3


@pytest.mark.parametrize("status", [400, 404])
def test_FR_MTG_09_MH_13_a_400_or_404_on_the_insert_is_final_one_request_never_retried(status):
    host = make_host_env()
    flow = host.prepare()
    host.cal.fail_next(status, times=5)

    assert states(host.settle(flow)) == ["failed"]

    assert len(host.cal.requests) == 1
    assert isinstance(host.recorder.errors[0], errs().SideEffectRefused)
    assert not isinstance(host.recorder.errors[0], errs().PossiblySent) and host.alerts == []
    assert host.outbox.dispatch_due() == [] and len(host.cal.requests) == 1
    assert host.transfers() == [] and host.stored_receipts() == []


@pytest.mark.parametrize(("status", "headers"), [(429, {"retry-after": "7"}), (500, None), (503, None)])
def test_FR_MTG_09_a_429_or_5xx_is_retried_later_and_Google_ends_with_one_event(status, headers):
    host = make_host_env()
    flow = host.prepare()
    host.cal.fail_next(status, headers=headers)
    enqueue(host.outbox, flow.case)

    assert host.outbox.dispatch_due() == [], "not failed, not sent: it waits"
    assert host.store.get(flow.entry["id"])["state"] not in ("sent", "failed")
    assert host.transfers() == []

    assert states(host.outbox.dispatch_due()) == ["sent"]
    assert len(host.cal.created()) == 1 and len(host.cal.invitations()) == 3 and len(host.stored_receipts()) == 1


def test_FR_MTG_09_a_403_is_never_a_sent_entry_a_receipt_or_a_second_event():
    host = make_host_env()
    flow = host.prepare()
    host.cal.fail_next(403, times=3)
    enqueue(host.outbox, flow.case)

    for _ in range(3):
        host.outbox.dispatch_due()

    assert host.store.get(flow.entry["id"])["state"] != "sent"
    assert host.transfers() == [] and host.stored_receipts() == [] and host.cal.created() == []


def test_FR_MTG_09_MH_13_a_409_means_an_earlier_attempt_created_it_so_the_adapter_reads_it_and_never_inserts_again():
    host = make_host_env()
    flow = host.prepare()
    marker = marker_of(flow.entry)
    host.cal.seed_event(marker)  # the earlier attempt created it and sent its invitations
    enqueue(host.outbox, flow.case)

    assert states(host.outbox.dispatch_due()) == ["sent"]

    assert len(host.cal.posts()) == 1 and len(host.cal.gets()) == 1, "one insert (the 409), one read"
    get = host.cal.gets()[0]
    assert get.url == EVENTS_URL + "/" + marker and get.params == {"fields": oracle_params()["fields"]}
    assert host.cal.created() == [] and host.cal.invitations() == [], "no second event, no second invitation"
    receipt = host.stored_receipts()[0]
    assert receipt.event_ref == marker and receipt.conference == "success"
    assert len(host.transfers()) == 1


@pytest.mark.parametrize("how", ["cancelled", "missing"])
def test_FR_MTG_09_MH_13_a_409_whose_event_is_cancelled_or_missing_is_PossiblySent_final_with_an_alert(how):
    host = make_host_env()
    flow = host.prepare()
    marker = marker_of(flow.entry)
    host.cal.seed_event(marker, status="cancelled" if how == "cancelled" else "confirmed")
    host.cal.get_hides_events = how == "missing"
    enqueue(host.outbox, flow.case)

    assert states(host.outbox.dispatch_due()) == ["failed"]

    assert len(host.cal.posts()) == 1, "no second insert, ever"
    assert isinstance(host.recorder.errors[0], errs().PossiblySent)
    assert [a["data"]["alert_id"] for a in host.alerts] == [flow.entry["id"]], "a person checks by hand"
    assert host.transfers() == [] and host.stored_receipts() == []
    assert host.outbox.dispatch_due() == [] and len(host.cal.posts()) == 1


def test_FR_MTG_09_MH_13_a_lost_answer_is_ambiguous_then_the_409_path_finds_the_event():
    host = make_host_env()
    flow = host.prepare()
    host.cal.lose_answer_after_create()
    enqueue(host.outbox, flow.case)

    assert host.outbox.dispatch_due() == [], "ProviderUnavailable: ambiguous, retried"
    assert isinstance(host.recorder.errors[0], errs().ProviderUnavailable)
    assert host.transfers() == [] and host.stored_receipts() == []
    assert states(host.outbox.dispatch_due()) == ["sent"]

    assert len(host.cal.created()) == 1
    assert sorted(a for _e, a in host.cal.invitations()) == sorted(flow.draft.recipients), "invited once each"
    assert len(host.stored_receipts()) == 1 and len(host.transfers()) == 1
    assert [p.method for p in host.cal.requests] == ["POST", "POST", "GET"]


# ---------------------------------------------------------------------------
# MH-14 the answer, step 8 the receipt, step 9 the return


def test_FR_MTG_09_MH_14_an_answer_whose_id_is_not_the_marker_is_PossiblySent():
    host = make_host_env()
    flow = host.prepare()
    host.cal.answer_id = "0" * 32
    enqueue(host.outbox, flow.case)

    assert states(host.outbox.dispatch_due()) == ["failed"]

    assert isinstance(host.recorder.errors[0], errs().PossiblySent)
    assert [a["data"]["alert_id"] for a in host.alerts] == [flow.entry["id"]]
    assert host.transfers() == [] and host.stored_receipts() == []


@pytest.mark.parametrize(
    ("google_says", "kept"),
    [("success", "success"), ("pending", "pending"), ("failure", "failure"), ("weird", "pending"), (None, "pending")],
)
def test_FR_MTG_09_MH_14_the_conference_status_is_Googles_when_it_is_pending_success_or_failure_else_pending(
    google_says, kept
):
    host = make_host_env(conference=google_says)
    flow = host.prepare()

    assert states(host.settle(flow)) == ["sent"], "even a failed conference is sent: the invitations went out"

    assert host.stored_receipts()[0].conference == kept
    assert host.recorder.results[0]["conference"] == kept
    assert len(host.transfers()) == 1


def test_FR_MTG_09_step_8_a_receipt_store_that_fails_is_retried_and_the_event_is_not_made_twice():
    receipts = FlakyReceipts(RuntimeError("store is down"), failures=1)
    host = make_host_env(receipts=receipts)
    flow = host.prepare()
    enqueue(host.outbox, flow.case)

    assert host.outbox.dispatch_due() == [], "an exception from put other than SideEffectRefused propagates"
    assert host.store.get(flow.entry["id"])["state"] not in ("sent", "failed") and host.transfers() == []
    assert states(host.outbox.dispatch_due()) == ["sent"]

    assert len(host.cal.created()) == 1 and len(host.cal.invitations()) == 3
    assert len(receipts.receipts()) == 1 and len(host.transfers()) == 1
    assert [p.method for p in host.cal.requests] == ["POST", "POST", "GET"]


def test_FR_MTG_09_step_8_a_receipt_store_that_refuses_ends_the_entry_failed_with_no_transfer():
    receipts = FlakyReceipts(errs().SideEffectRefused("a different receipt is already stored"), failures=9)
    host = make_host_env(receipts=receipts)
    flow = host.prepare()

    assert states(host.settle(flow)) == ["failed"]

    assert host.transfers() == [] and receipts.receipts() == []


# ---------------------------------------------------------------------------
# Static: the adapter module (offline, silent, model-free, no password)


def test_FR_MTG_09_the_adapter_modules_import_no_model_harness_planner_network_or_logging():
    from _meeting_host_lib import SRC, import_roots, module_source

    forbidden_roots = {"tilo_providers", "tilo_harness", "tilo_planning", "logging", "socket", "requests", "httpx"}
    for path in (SRC / "meeting_host.py", SRC / "adapters" / "meeting_host.py"):
        roots = {name.lstrip(".").split(".")[0] for name in import_roots(path)}
        assert not (roots & forbidden_roots), f"{path.name} imports {sorted(roots & forbidden_roots)}"
        source = module_source(path)
        assert "print(" not in source and "getLogger" not in source, "no log line anywhere in the module"


def test_FR_MTG_09_the_adapter_module_holds_the_only_calendar_write_and_names_no_password():
    from _meeting_host_lib import SRC, module_source

    adapter = module_source(SRC / "adapters" / "meeting_host.py")
    assert "calendar.events" in module_source(SRC / "meeting_host.py")
    assert re.search(r"passw|secret_key", adapter + module_source(SRC / "meeting_host.py"), re.I) is None


def test_FR_MTG_09_the_one_scope_is_calendar_events_owned_and_no_meet_api_scope_is_named():
    from _meeting_host_lib import SRC, module_source

    for name in ("meeting_host.py", "adapters/meeting_host.py"):
        source = module_source(SRC / name)
        assert "meetings.space" not in source and "meet.created" not in source and "auth/meetings" not in source
        assert "auth/calendar.events" not in source.replace("auth/calendar.events.owned", ""), "no wider scope"


# ---------------------------------------------------------------------------
# A model-free, link-free draft artifact end to end (the store double enforces AR-01)


def test_FR_MTG_09_the_hash_checked_read_is_what_the_adapter_sends_from_not_the_card_text():
    host = make_host_env()
    flow = host.prepare()
    enqueue(host.outbox, flow.case)

    host.outbox.dispatch_due()

    assert set(host.artifacts.reads) == {(flow.gate["item"]["artifact_id"], flow.gate["item"]["version"])}
    assert ATTACKER not in json.dumps(host.cal.posts()[0].json)
    assert SAM_MAIL in json.dumps(host.cal.posts()[0].json)


# ---------------------------------------------------------------------------
# The address limit: 50 recipients, the card and outbox maximum


def test_FR_MTG_09_fifty_recipients_are_sent_whole_in_one_insert_and_the_card_still_validates():
    attendees, extra = many_users(49)
    host = make_host_env()
    flow = host.prepare(meeting(attendees=attendees), {**default_persons(), **extra})

    assert states(host.settle(flow)) == ["sent"]

    (post,) = host.cal.posts()
    assert len(post.json["attendees"]) == 50 == len(flow.card["gate"]["recipients"])
    assert [a["email"] for a in post.json["attendees"]] == flow.card["gate"]["recipients"]
    assert schema_errors("card.schema.json", flow.card) == [] and len(flow.gate["exact"]) <= 500
    assert len(host.cal.invitations()) == 50


def test_FR_MTG_09_an_entry_of_51_recipients_is_refused_at_enqueue_so_it_can_never_reach_Google():
    host = make_host_env()
    flow = host.prepare()
    case = copy.deepcopy(flow.case)
    case["entry"]["recipients"] = [f"p{i:02d}@example.com" for i in range(51)]

    with pytest.raises(OutboxRefused):
        enqueue(host.outbox, case)

    assert host.store.all_entries() == []
    assert host.outbox.dispatch_due() == []
    nothing_sent(host)
