"""FR-MTG-09 (MTG09-b, API half), the Opus security review's second pass: a hosted meeting's gate outlives nothing.

- host -> delete the meeting -> approve: the run ends before anything is sent (no entry, no calendar request, no
  `data.transfer`), and the host draft (title, time, every invitee address) and the receipt are purged with the meeting.
- The owner cannot share the host gate with an Approver (ADR-0024: no Approver opens it).
- `on_connection_event` never raises on a store error and leaves an ambiguous entry to the alert path.
- A run that cannot start leaves no permanent 409.
"""

from __future__ import annotations

import types

import pytest
from _clint2_lib import wait_for
from _mtg09b_lib import ASHA, CONNECTOR_ID, MEETING, PRIYA_MAIL, WORLD, HostRig, block_network
from _ppl11a_lib import DEV, OWNER
from tilo_api import meeting_host
from tilo_memory.artifacts import ArtifactNotFound


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    block_network(monkeypatch)


@pytest.fixture()
def hr(people_rig):
    return HostRig(people_rig())


def _delete(hr: HostRig):
    hr.rig.as_user(OWNER)
    return hr.rig.client.post(f"/v1/meetings/{MEETING}/delete", json={})


def _stored_anything(hr: HostRig) -> list[str]:
    return [p for p in hr.art.meta.paths("") if "/artifacts/" in p]


def test_FR_MTG_09_deleting_a_meeting_with_a_pending_host_gate_ends_the_run_before_anything_is_sent(hr):
    card = hr.host_and_wait_gate()
    ref, _, _ = hr.draft()
    assert _delete(hr).status_code == 200
    assert _stored_anything(hr) == [], "the host draft is purged with the meeting"
    with pytest.raises(ArtifactNotFound):
        hr.art.store.read(hr.scope(), ref)
    assert hr.answer(card["id"], "approve").status_code in (200, 409)
    wait_for(lambda: hr.events("world.failed"), what="the run to end")
    hr.quiet()
    assert hr.entries() == [] and hr.calendar.requests == [] and hr.broker.calls == []
    assert hr.events("data.transfer") == [] and hr.receipt_refs() == []
    assert _stored_anything(hr) == []


def test_FR_MTG_09_deleting_a_meeting_after_the_send_purges_the_draft_and_the_receipt(hr):
    hr.approve_and_wait_sent()
    hr.quiet()
    (receipt,) = hr.receipt_refs()
    ref, _, _ = hr.draft()
    assert _delete(hr).status_code == 200
    assert _stored_anything(hr) == []
    for gone in (ref, receipt):
        assert hr.art.store.head(hr.scope(), gone) is None


def test_FR_MTG_09_the_host_gate_cannot_be_shared_with_an_approver(hr):
    card = hr.host_and_wait_gate()
    hr.sign_in_world()
    shared = hr.rig.client.post(f"/worlds/{WORLD}/cards/{card['id']}/share", json={"approver": DEV})
    assert shared.status_code == 409 and shared.json()["reason"] == "owner_only_gate", shared.text[:200]
    assert [c["id"] for c in hr.gate_cards()] == [card["id"]], "no second card for an Approver"
    assert len(hr.events("approval.requested")) == 1 and "token" not in shared.text
    assert hr.entries() == [] and hr.calendar.requests == []


def test_FR_MTG_09_the_disconnect_handler_survives_a_store_error_and_leaves_an_ambiguous_entry(hr):
    handler = meeting_host.on_connection_event
    card = hr.host_and_wait_gate()
    hr.broker.connected = False
    assert hr.answer(card["id"], "approve").status_code == 200
    entry = wait_for(lambda: hr.entries() or None, what="the outbox entry")[0]

    class Broken:
        def all_entries(self):
            raise RuntimeError("the store is down")

    assert handler(hr.broker.revoked_part(OWNER), outbox_store=Broken()) == 0
    hr.outbox_store._retries[entry["id"]] = {"ambiguous": True}  # noqa: SLF001 - a send that may have gone out
    assert handler(hr.broker.revoked_part(OWNER), outbox_store=hr.outbox_store) == 0
    assert hr.entries()[0]["state"] not in ("failed", "cancelled", "sent")
    assert CONNECTOR_ID == entry["connector"] and hr.calendar.requests == []


def test_FR_MTG_09_a_run_that_cannot_start_leaves_no_permanent_409(hr, monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("no thread")

    real = meeting_host.threading
    monkeypatch.setattr(meeting_host, "threading", types.SimpleNamespace(Thread=boom))
    assert hr.host().status_code == 503
    assert hr.store.runs == {}
    monkeypatch.setattr(meeting_host, "threading", real)
    assert hr.host().status_code == 200
    assert ASHA not in str(hr.wait_gate()["what_happened"]) and PRIYA_MAIL not in str(hr.events())
