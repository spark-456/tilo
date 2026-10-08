"""FR-MTG-09 (MTG09-b, API half): consent revoked mid-flight and a conference that failed (API_MTG09_b.md;
services/connectors/tests/API_FR_MTG_09.md "Consent revoked mid-flight" and the adapter's step 9).

- `broker.disconnect(owner, "meeting_host")` after approval and before the dispatch: the dispatch asks the broker and
  gets `NotConnected` (no request, no attempt spent); the API's disconnect handler, `tilo_api.meeting_host.
  on_connection_event(part, *, outbox_store)`, abandons the unsent entry: `failed`, no `data.transfer`, no receipt, and
  a later reconnect sends nothing for it. It touches nothing but this owner's unsent `meeting_host` entries.
- `conference: failure` is still `sent` (Google created the event and sent the invitations); the run raises one
  `needs_you` card, "Google did not add a Meet link", naming no link, address or title.
"""

from __future__ import annotations

import importlib
import json

import pytest
from _clint2_lib import schema_errors, wait_for
from _mtg09b_lib import (
    ASHA,
    CONNECTOR_ID,
    PLANTED_HTML,
    PLANTED_LINK,
    PRIYA_MAIL,
    SAM_MAIL,
    TITLE,
    HostRig,
    block_network,
)
from _ppl11a_lib import OWNER, SAM


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    block_network(monkeypatch)


@pytest.fixture()
def hr(people_rig):
    return HostRig(people_rig())


def _handler():
    return importlib.import_module("tilo_api.meeting_host").on_connection_event


def _unsent_after_a_revoked_grant(hr: HostRig) -> dict:
    """Host, then the grant goes away before the approved send is dispatched: the entry waits, unsent."""
    card = hr.host_and_wait_gate()
    hr.broker.connected = False  # the consent was withdrawn at Google; the revoked event has not reached tilo-api yet
    assert hr.answer(card["id"], "approve").status_code == 200
    entry = wait_for(lambda: hr.entries() or None, what="the outbox entry")[0]
    wait_for(lambda: hr.broker.calls or None, what="the dispatch to ask the broker")
    entry = hr.entries()[0]
    assert entry["state"] not in ("sent", "failed", "cancelled"), "unsent, waiting for a person (no attempt spent)"
    assert hr.calendar.requests == []
    return entry


def test_FR_MTG_09_a_revoked_grant_abandons_the_unsent_entry_and_a_reconnect_sends_nothing(hr):
    handler = _handler()
    entry = _unsent_after_a_revoked_grant(hr)
    counts: list[int] = []
    hr.broker.emit = lambda part: counts.append(handler(part, outbox_store=hr.outbox_store))  # the broker's emit sink

    def disconnect() -> bool:
        hr.broker.disconnect(OWNER, CONNECTOR_ID)  # flips the grant and hands connection.revoked to the sink
        return hr.entries()[0]["state"] == "failed"

    wait_for(
        disconnect, timeout=3, what="the unsent entry to be abandoned"
    )  # a retry only if a dispatch held the lease
    assert sum(counts) == 1, "exactly the one unsent entry"
    (failed,) = hr.entries()
    assert failed["id"] == entry["id"] and failed["state"] == "failed"
    assert hr.calendar.requests == [] and hr.calendar.invitations == {}, "the dispatch made no request"
    assert hr.events("data.transfer") == [] and hr.receipt_refs() == [], "no data.transfer and no receipt"
    hr.broker.connected = True  # the owner reconnects later
    hr.quiet(1.0)
    assert hr.calendar.requests == [] and hr.events("data.transfer") == []
    assert hr.entries()[0]["state"] == "failed", "reconnecting sends nothing for it"


def test_FR_MTG_09_the_disconnect_handler_touches_only_this_owners_unsent_host_entries(hr):
    handler = _handler()
    _unsent_after_a_revoked_grant(hr)
    base = {"authz": None, "user_id": OWNER}
    other_connector = {**base, "type": "connection.revoked", "data": {"connector": "gmail"}}
    other_user = {**base, "user_id": SAM, "type": "connection.revoked", "data": {"connector": CONNECTOR_ID}}
    not_a_revoke = {**base, "type": "connection.established", "data": {"connector": CONNECTOR_ID}}
    for part in (other_connector, other_user, not_a_revoke):
        assert handler(part, outbox_store=hr.outbox_store) == 0, part
    assert hr.entries()[0]["state"] not in ("failed", "cancelled", "sent"), "another connector, person or event"
    for hostile in ({"type": "connection.revoked"}, {"type": "connection.revoked", "data": None}, {}, "revoked", None):
        assert handler(hostile, outbox_store=hr.outbox_store) == 0, hostile  # a malformed part abandons nothing
    assert hr.entries()[0]["state"] not in ("failed", "cancelled", "sent")
    assert hr.calendar.requests == []


def test_FR_MTG_09_a_revoked_grant_with_nothing_unsent_is_a_no_op(hr):
    handler = _handler()
    assert handler(hr.broker.revoked_part(OWNER), outbox_store=hr.outbox_store) == 0
    hr.approve_and_wait_sent()
    hr.quiet()
    assert handler(hr.broker.revoked_part(OWNER), outbox_store=hr.outbox_store) == 0, "a sent entry is never touched"
    assert [e["state"] for e in hr.entries()] == ["sent"] and len(hr.events("data.transfer")) == 1


# --- conference: failure ---


def test_FR_MTG_09_a_conference_that_failed_raises_one_needs_you_card_and_the_entry_stays_sent(hr):
    hr.calendar.conference = "failure"
    hr.approve_and_wait_sent()
    cards = wait_for(
        lambda: [c for c in hr.cards() if c["kind"] == "needs_you"] or None, what="the needs-you card for the Meet link"
    )
    hr.quiet()
    cards = [c for c in hr.cards() if c["kind"] == "needs_you"]
    assert len(cards) == 1, "one card, not one per poll"
    card = cards[0]
    assert "Google did not add a Meet link" in card["what_happened"]
    assert card["rung"] == "needs_you" and card["world_id"] and schema_errors("card", card) == []
    text = json.dumps(card)
    for forbidden in (PLANTED_LINK, PLANTED_HTML, ASHA, PRIYA_MAIL, SAM_MAIL, TITLE, "meet.google.com"):
        assert forbidden not in text, "ids only: the card names no link, address or title"
    (entry,) = hr.entries()
    assert entry["state"] == "sent" and len(hr.events("data.transfer")) == 1, "Google did send the invitations"
    assert len(hr.calendar.requests) == 1 and sum(hr.calendar.invitations.values()) == 3
    assert hr.receipt_refs(), "the receipt is stored with the failed status"
    (rref,) = hr.receipt_refs()
    assert json.loads(hr.art.store.read(hr.scope(), rref))["conference"] == "failure"


@pytest.mark.parametrize("status", ["success", "pending"])
def test_FR_MTG_09_a_conference_that_did_not_fail_raises_no_needs_you_card(hr, status):
    hr.calendar.conference = status
    hr.approve_and_wait_sent()
    hr.quiet(1.0)
    assert [c for c in hr.cards() if c["kind"] == "needs_you"] == []
    assert json.loads(hr.art.store.read(hr.scope(), hr.receipt_refs()[0]))["conference"] == status
