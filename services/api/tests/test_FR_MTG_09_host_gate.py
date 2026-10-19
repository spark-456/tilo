"""FR-MTG-09 (MTG09-b, API half): the hosted meeting's one gate, from the route to the receipt (API_MTG09_b.md,
services/connectors/tests/API_FR_MTG_09.md "Ordered flow" steps 3 to 9 and acceptance (a), (b), (c)).

Given a scheduled bot meeting of u_owner with the fake `meeting_host` seams, When the owner hosts it, Then a fixed
one-unit plan (no Director call) stores the draft and holds ONE T3 gate card whose text, recipients and item are the
draft's; nothing is sent before an approving answer; on approve the outbox sends exactly one insert with exactly the
recipients the card showed; the Meet link is stored nowhere; the receipt traces back to the approval.
"""

from __future__ import annotations

import json
import re

import pytest
from _clint2_lib import covering_policy, schema_errors, wait_for
from _mtg09b_lib import (
    ACTION_TYPE,
    ASHA,
    ATTACKER,
    CALENDAR_EVENTS_OWNED,
    CONNECTOR_ID,
    DEV_MAIL,
    DRAFT_KEY,
    EVENTS_URL,
    INSERT_PARAMS,
    IST,
    MEETING,
    PLANTED_HTML,
    PLANTED_LINK,
    PRIYA_MAIL,
    RUN,
    SAM_MAIL,
    TITLE,
    WHEN_IST,
    WORLD,
    HostRig,
    LogCatcher,
    assert_registered_and_valid,
    attendees_of,
    block_network,
    canonical,
    expected_draft,
    expected_exact,
    expected_insert_body,
    marker_of,
    meeting,
    stored_text,
)
from _ppl11a_lib import DEV, OWNER, PRIYA, SAM, Rig
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from tilo_api.deps import Principal

ADDRESSES = (ASHA, PRIYA_MAIL, SAM_MAIL, DEV_MAIL, ATTACKER)


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    block_network(monkeypatch)


@pytest.fixture()
def hr(people_rig):
    return HostRig(people_rig())


def _item(card: dict) -> dict:
    return {k: card["gate"]["action"]["item"][k] for k in ("artifact_id", "version")}


# --- (a) nothing before approval ---


@pytest.mark.parametrize("answer", [None, "hold", "edit"], ids=["unanswered", "hold", "edit"])
def test_FR_MTG_09_a_nothing_is_sent_before_an_approving_answer(hr, answer):
    hr.rig.require_route(("POST", "/v1/meetings/{meeting_id}/host"))
    card = hr.host_and_wait_gate()
    assert len(hr.events("approval.requested")) == 1
    if answer is not None:
        assert hr.answer(card["id"], answer).status_code == 200
    hr.quiet()
    assert hr.entries() == [], "no outbox entry before an approving approval.resolved (OB-01)"
    assert hr.calendar.requests == [] and hr.calendar.invitations == {}
    assert hr.broker.calls == [], "no token is even asked for"
    assert hr.events("data.transfer") == [] and hr.receipt_refs() == []
    assert hr.events("approval.resolved") == [], "only an approve writes approval.resolved (CR-07)"


def test_FR_MTG_09_a_the_plan_is_fixed_one_gate_and_no_model_is_asked(hr):
    hr.rig.require_route(("POST", "/v1/meetings/{meeting_id}/host"))
    hr.host_and_wait_gate()
    hr.quiet()
    assert hr.compile_calls == [] and hr.runner_calls == [], "no Director call and no worker model (D-6 pattern)"
    assert [c["kind"] for c in hr.cards()] == ["gate"], "one gate card, no question and no needs-you card"
    assert len(hr.events("approval.requested")) == 1
    assert hr.rig.router_calls == [], "no model router is ever built"
    assert hr.store.worlds[WORLD].owner == OWNER and RUN in {e["run_id"] for e in hr.events()}, "the world's run id"


# --- (b) the card, the entry and the request are one thing ---


def test_FR_MTG_09_b_the_gate_card_shows_exactly_what_will_be_sent(hr):
    card = hr.host_and_wait_gate()
    ref, record, content = hr.draft()
    recipients = [ASHA, PRIYA_MAIL, SAM_MAIL]
    assert content == canonical(expected_draft(recipients)), "the draft artifact is the canonical JSON the doc pins"
    assert record["media_type"] == "application/json" and record["origin"]["kind"] == "unit"
    assert DRAFT_KEY.fullmatch(record["idempotency_key"]), record["idempotency_key"]  # AR-05: run:unit:attempt:0
    assert record["run_id"] == RUN
    gate, action = card["gate"], card["gate"]["action"]
    assert {k: v for k, v in action.items() if k != "item"} == {
        "type": ACTION_TYPE,
        "connector": CONNECTOR_ID,
        "exact": expected_exact(TITLE, WHEN_IST, IST, 3, 1),
        "destination": "primary",
    }, "`exact` is the draft's sentence (not the generic `_exact`), the destination the host calendar"
    assert _item(card) == ref
    assert gate["recipients"] == recipients, "the owner first, then the scheduled attendees with a Tilo account"
    assert (gate["risk_tier"], gate["irreversible"]) == ("T3", True)
    assert card["kind"] == "gate" and card["answer_channels"] == ["web", "mobile_web"]
    assert card["safe_default"] == "hold" and {o["id"] for o in card["options"]} == {"approve", "edit", "hold"}
    assert card["world_id"] == WORLD and card["run_id"] == RUN
    assert schema_errors("card", card) == []
    text = json.dumps(card)
    assert DEV_MAIL not in text and ATTACKER not in text, "a person of the org who is not on the meeting is not invited"
    requested = hr.requested()["data"]
    assert (requested["risk_tier"], requested["irreversible"], requested["action_type"]) == ("T3", True, ACTION_TYPE)
    assert requested["item"] == ref and requested["card_id"] == card["id"]
    assert requested["approver"] is None and requested["team_lead"] is None


def test_FR_MTG_09_b_an_approved_gate_makes_exactly_the_insert_the_card_showed(hr):
    card = hr.approve_and_wait_sent()
    hr.quiet()
    ref, _, content = hr.draft()
    draft = json.loads(content)
    (entry,) = hr.entries()
    (request,) = hr.calendar.requests
    assert (request["method"], request["url"]) == ("POST", EVENTS_URL)
    assert request["params"] == INSERT_PARAMS
    assert request["json"] == expected_insert_body(entry, draft), "the body is the pinned draft, nothing more"
    emails = [a["email"] for a in request["json"]["attendees"]]
    assert emails == card["gate"]["recipients"] == entry["recipients"] == draft["attendees"]
    assert request["json"]["conferenceData"]["createRequest"]["conferenceSolutionKey"] == {"type": "hangoutsMeet"}
    assert request["headers"]["authorization"] == "Bearer " + hr.broker.token
    assert hr.broker.calls == [(OWNER, CONNECTOR_ID, (CALENDAR_EVENTS_OWNED,), False)], "the owner's host grant only"
    assert hr.calendar.invitations == {marker_of(entry): 3}, "one event, one invitation per recipient"
    (resolved,) = hr.events("approval.resolved")
    assert resolved["authz"]["by"] == "person" and resolved["authz"]["ref"] == OWNER
    assert (entry["state"], entry["action_type"], entry["connector"]) == ("sent", ACTION_TYPE, CONNECTOR_ID)
    assert (entry["risk_tier"], entry["modifiers"], entry["destination"]) == ("T3", ["new_recipients"], "primary")
    assert entry["attachments"] == [] and entry["undo_window_s"] == 0 and entry["authz"] == resolved["authz"]
    assert {k: entry["item"][k] for k in ("artifact_id", "version")} == ref == _item(card)
    (transfer,) = hr.events("data.transfer")
    assert transfer["authz"] == resolved["authz"], "the transfer carries the approval's authz"
    assert {k: transfer["data"]["artifact"][k] for k in ("artifact_id", "version")} == ref
    assert transfer["data"]["connector"] == CONNECTOR_ID and transfer["data"]["action_type"] == ACTION_TYPE
    assert "recipients" not in json.dumps(transfer), "a transfer names no one"


def test_FR_MTG_09_b_the_list_the_owner_approved_is_the_list_sent(hr):
    card = hr.host_and_wait_gate()
    stored = hr.rig.stored("meetings", MEETING)
    edited = {**stored, "title": "Renamed", "attendees": attendees_of(OWNER, PRIYA, SAM, DEV)}
    hr.rig.real.meetings.replace(edited, expected_version=1)
    assert hr.answer(card["id"], "approve").status_code == 200
    wait_for(lambda: hr.events("data.transfer"), what="data.transfer")
    (request,) = hr.calendar.requests
    assert [a["email"] for a in request["json"]["attendees"]] == [ASHA, PRIYA_MAIL, SAM_MAIL], "the pinned draft"
    assert request["json"]["summary"] == TITLE


def test_FR_MTG_09_b_only_the_owners_signed_in_answer_opens_the_gate(hr):
    card = hr.host_and_wait_gate()
    others = [
        Principal(user_id=SAM, role="owner", world_id=WORLD),  # another person claiming the world's owner role
        Principal(user_id=DEV, role="approver", world_id=WORLD),
        Principal(user_id=SAM, role="viewer", world_id=WORLD),
        Principal(user_id=OWNER, role="owner", world_id=WORLD, channel="email"),  # an email answer opens nothing
    ]
    for principal in others:
        hr.principal_as(principal)
        body = {"option": "approve", "channel": principal.channel}
        response = hr.rig.client.post(f"/worlds/{WORLD}/cards/{card['id']}/answer", json=body)
        assert response.status_code != 200, (principal, response.text[:200])
        assert response.json().get("outcome") != "answered"
    hr.restore_principal()
    hr.quiet()
    assert hr.events("approval.resolved") == [] and hr.entries() == [] and hr.calendar.requests == []
    assert hr.answer(card["id"], "approve").status_code == 200, "the refusals did not use the card up"
    wait_for(lambda: hr.events("data.transfer"), what="data.transfer")
    assert len(hr.calendar.requests) == 1


@pytest.mark.parametrize("level", ["L2", "L3"])
def test_FR_MTG_09_b_a_policy_never_opens_the_host_gate(hr, level):
    stamp = {"by": OWNER, "at": "2026-09-29T09:30:00.000Z"}
    policy = {
        **covering_policy(OWNER),
        "id": "pol_host_auto",
        "action_type": ACTION_TYPE,
        "level": level,
        "scope": {
            "connectors": [CONNECTOR_ID],
            "recipients": [ASHA, PRIYA_MAIL, SAM_MAIL],  # covers every recipient of the hosted meeting
            "domains": [],
            "districts": [],
        },
        "limits": {"per_day": 20, "credits": 50} if level == "L2" else {"per_day": 5, "credits": None},
        "expiry": "2030-12-31T23:59:59.000Z" if level == "L2" else None,
        "history": [{**stamp, "change": f"Created at {level}", "level": level}],
    }
    assert schema_errors("policy", policy) == [], "the policy under test is a valid policy"
    hr.store.policies["pol_host_auto"] = policy
    card = hr.host_and_wait_gate()
    hr.quiet()
    assert card["kind"] == "gate" and card["gate"]["risk_tier"] == "T3", "T3 allows at most L1 (PE-14, OB-04)"
    assert hr.entries() == [] and hr.calendar.requests == [] and hr.events("policy.applied") == []
    assert hr.answer(card["id"], "approve").status_code == 200
    wait_for(lambda: hr.events("data.transfer"), what="data.transfer")
    assert hr.events("data.transfer")[0]["authz"]["by"] == "person"
    assert hr.entries()[0]["authz"]["by"] == "person"


# --- who is invited ---


def _expected(users: list[str | None], unresolved: int) -> tuple[list[str], int]:
    mail = {OWNER: ASHA, PRIYA: PRIYA_MAIL, SAM: SAM_MAIL, DEV: DEV_MAIL}
    out = [OWNER]
    out += [u for u in dict.fromkeys(users) if u is not None and u != OWNER]
    return [mail[u] for u in out], unresolved


@pytest.mark.parametrize(
    ("attendees", "recipients", "not_invited"),
    [
        (attendees_of(OWNER, PRIYA, SAM, unresolved=("Dev from Acme",)), [ASHA, PRIYA_MAIL, SAM_MAIL], 1),
        (attendees_of(PRIYA, SAM), [ASHA, PRIYA_MAIL, SAM_MAIL], 0),  # the owner is always invited, first
        (attendees_of(SAM, PRIYA, OWNER), [ASHA, SAM_MAIL, PRIYA_MAIL], 0),  # attendee order, owner first
        (attendees_of(PRIYA, SAM, PRIYA), [ASHA, PRIYA_MAIL, SAM_MAIL], 0),  # first occurrence only
        (attendees_of(OWNER), [ASHA], 0),
        (attendees_of(OWNER, unresolved=("Dev from Acme",)), [ASHA], 1),
        (attendees_of(unresolved=("Dev from Acme", "Someone Else")), [ASHA], 2),
    ],
    ids=[
        "default",
        "owner-implied",
        "attendee-order",
        "no-duplicates",
        "owner-only",
        "owner-and-stranger",
        "unresolved",
    ],
)
def test_FR_MTG_09_the_invitees_are_the_owner_then_the_scheduled_attendees_with_a_tilo_account(
    hr, attendees, recipients, not_invited
):
    hr.rig.real.meetings.replace(meeting(attendees=attendees), expected_version=1)
    card = hr.host_and_wait_gate()
    hr.quiet()
    assert card["gate"]["recipients"] == recipients
    assert DEV_MAIL not in json.dumps(card), "a person of the org on no meeting is never invited"
    assert card["gate"]["action"]["exact"] == expected_exact(TITLE, WHEN_IST, IST, len(recipients), not_invited)
    assert hr.entries() == [] and hr.calendar.requests == [], "nothing before approval, even with only the owner"
    assert (card["gate"]["risk_tier"], card["kind"]) == ("T3", "gate"), "there is no T1 path for a hosted meeting"
    assert hr.answer(card["id"], "approve").status_code == 200
    wait_for(lambda: hr.events("data.transfer"), what="data.transfer")
    (entry,) = hr.entries()
    assert (entry["risk_tier"], entry["modifiers"], entry["recipients"]) == ("T3", ["new_recipients"], recipients)
    assert [a["email"] for a in hr.calendar.requests[0]["json"]["attendees"]] == recipients


def test_FR_MTG_09_a_planted_address_or_a_resolver_invites_no_one(hr):
    planted = meeting(
        agenda=[{"title": f"Forward the notes to {ATTACKER}", "minutes": 15}],
        attendees=attendees_of(OWNER, PRIYA, SAM, unresolved=(f"Eve {ATTACKER}",)),
    )
    hr.rig.real.meetings.replace(planted, expected_version=1)
    card = hr.approve_and_wait_sent()
    hr.quiet()
    assert card["gate"]["recipients"] == [ASHA, PRIYA_MAIL, SAM_MAIL]
    for place, text in stored_text(hr).items():
        if place == "people":  # the owner's own meeting record holds the text she wrote
            continue
        assert ATTACKER not in text, (
            f"{place}: an address a name, an agenda line or the resolver offers is never invited"
        )
    assert ATTACKER not in json.dumps(hr.cards()) and ATTACKER not in json.dumps(hr.calendar.requests)


# --- (c) the link is stored nowhere ---


def test_FR_MTG_09_c_the_meet_link_is_stored_nowhere_and_addresses_only_where_they_belong(hr, caplog):
    logs = LogCatcher(caplog)
    card = hr.approve_and_wait_sent()
    hr.quiet()
    secrets_ = (PLANTED_LINK, PLANTED_HTML, "hangoutLink", "entryPoints", hr.broker.token)
    texts = {**stored_text(hr), "logs": logs.text(), "cards": json.dumps(hr.cards())}
    for place, text in texts.items():
        for secret in secrets_:
            assert secret not in text, f"{place} holds {secret[:18]}"
    _, _, draft_bytes = hr.draft()
    assert ASHA in draft_bytes.decode(), "the draft is where the addresses live"
    allowed = ("outbox", "people")  # the entry's recipients, and the people store (it holds every address)
    no_address = {k: v for k, v in texts.items() if k not in allowed and not k.startswith("artifact-blob")}
    no_address["cards"] = json.dumps({**card, "gate": {**card["gate"], "recipients": []}})
    for place, text in no_address.items():
        for address in (ASHA, PRIYA_MAIL, SAM_MAIL):
            assert address not in text, f"{place} holds an attendee address"
    for ref in hr.receipt_refs():
        receipt = hr.art.store.read(hr.scope(), ref).decode()
        assert PLANTED_LINK not in receipt and ASHA not in receipt, "the receipt keeps Google's event id only"


def test_FR_MTG_09_c_no_event_names_a_title_a_link_or_an_address(hr):
    hr.approve_and_wait_sent()
    hr.quiet()
    for event in hr.events():
        text = json.dumps(event)
        assert not [
            s for s in (PLANTED_LINK, PLANTED_HTML, ASHA, PRIYA_MAIL, SAM_MAIL, "meet.google.com") if s in text
        ], (
            event["type"],
            text[:200],
        )


# --- the receipt traces back to the approval ---


def test_FR_MTG_09_the_receipt_and_the_draft_trace_back_to_the_approval(hr):
    hr.approve_and_wait_sent()
    hr.quiet()
    ref, _, _ = hr.draft()
    (rref,) = hr.receipt_refs()
    (entry,) = hr.entries()
    receipt = json.loads(hr.art.store.read(hr.scope(), rref))
    assert receipt == {
        "v": "1.0",
        "kind": "meeting_event_receipt",
        "connector": CONNECTOR_ID,
        "calendar": "primary",
        "event_ref": marker_of(entry),
        "meeting_id": MEETING,
        "draft": ref,
        "outbox_id": entry["id"],
        "conference": "success",
    }, "Google's event id and the draft ref: no link, no address, no title, no time"
    created = [e for e in hr.events("artifact.created") if e["data"]["artifact"]["artifact_id"] == rref["artifact_id"]]
    assert len(created) == 1 and created[0]["data"]["media_type"] == "application/json"
    scope = hr.scope()
    inputs = hr.art.store.manifest(scope, rref)["inputs"]
    assert [(i["artifact_id"], i["version"]) for i in inputs] == [(ref["artifact_id"], ref["version"])]
    (transfer,) = hr.events("data.transfer")
    latest = hr.art.store.manifest_revisions(scope, ref)[-1]
    assert latest["stage"] == "sent" and latest["cause"] == transfer["id"], "AR-06: the sent revision's cause"
    assert latest["manifest"]["authz"] == transfer["authz"], "MF-04"


def test_FR_MTG_09_every_event_the_host_run_wrote_is_registered_and_valid(hr, repo_root, registry):
    hr.approve_and_wait_sent()
    hr.quiet()
    stream = hr.events()
    assert_registered_and_valid(registry, repo_root, stream)
    assert [e["seq"] for e in stream] == list(range(1, len(stream) + 1)), "seq strictly increasing, no gaps"
    assert len({e["id"] for e in stream}) == len(stream)
    kinds = [e["type"] for e in stream]
    assert {"approval.requested", "approval.resolved", "data.transfer", "artifact.created"} <= set(kinds)
    assert kinds.index("approval.requested") < kinds.index("approval.resolved") < kinds.index("data.transfer")
    assert re.fullmatch(r"[0-9a-f]{32}", marker_of(hr.entries()[0]))


# --- property: the recipients are the rule's, never more ---


@settings(max_examples=8, deadline=None, suppress_health_check=list(HealthCheck))
@given(
    users=st.lists(st.sampled_from([OWNER, PRIYA, SAM, DEV, None]), min_size=1, max_size=8),
    unresolved=st.integers(min_value=0, max_value=3),
)
def test_FR_MTG_09_property_the_card_names_exactly_the_rule_and_nothing_is_sent_before_approval(users, unresolved):
    attendees = [{"name": u or "Guest", "user": u} for u in users]
    attendees += [{"name": f"Guest {n}", "user": None} for n in range(unresolved)]
    with pytest.MonkeyPatch.context() as mp:
        block_network(mp)
        rig = Rig(mp)
        host: HostRig | None = None
        try:
            host = HostRig(rig)
            rig.real.meetings.replace(meeting(attendees=attendees), expected_version=1)
            assert host.host().status_code == 200
            card = host.wait_gate()
            host.quiet(0.2)
            recipients, _ = _expected(users, unresolved)
            assert card["gate"]["recipients"] == recipients and len(recipients) <= 50
            assert len(set(recipients)) == len(recipients) and recipients[0] == ASHA
            assert ATTACKER not in json.dumps(card) and card["gate"]["risk_tier"] == "T3"
            assert host.entries() == [] and host.calendar.requests == [] and host.events("data.transfer") == []
        finally:
            if host is not None:
                host.store.worlds[WORLD].paused = True  # ends the run's wait
            rig.close()
