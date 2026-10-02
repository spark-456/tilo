"""CL-INT-2 review round 1 (#151; FR-WLD-07, FR-AGT-11): an Outbox scoped to one world dispatches and emits only
that world's entries and transfers, and `abandon` fails an unsent entry so no later dispatch sends it."""

from __future__ import annotations

from tilo_connectors import InMemoryOutboxStore, Outbox, OutboxRefused

NOW = "2026-10-02T09:00:00.000Z"


def _entry(outbox_id: str, world_id: str, state: str = "queued") -> dict:
    return {
        "id": outbox_id,
        "world_id": world_id,
        "idempotency_key": f"k_{outbox_id}",
        "connector": "c",
        "state": state,
    }


def _with_pending_transfer(store: InMemoryOutboxStore, outbox_id: str, world_id: str) -> None:
    store._insert_if_absent(_entry(outbox_id, world_id))
    assert store._claim_for_sending(outbox_id, "h", NOW, 30)
    store._finalize_claim(outbox_id, "h", "sent", {"type": "data.transfer", "data": {"outbox_id": outbox_id}})


def test_FR_WLD_07_a_world_scoped_outbox_emits_only_its_own_worlds_transfers():
    store, emitted = InMemoryOutboxStore(), []
    _with_pending_transfer(store, "o_b", "w_b")
    _with_pending_transfer(store, "o_a", "w_a")

    Outbox(store, {}, emit=emitted.append, clock=lambda: NOW, world_id="w_a").dispatch_due()

    assert [t["data"]["outbox_id"] for t in emitted] == ["o_a"]


def test_FR_WLD_07_a_world_scoped_outbox_dispatches_only_its_own_worlds_entries():
    store = InMemoryOutboxStore()
    store._insert_if_absent(_entry("o_a", "w_a"))
    store._insert_if_absent(_entry("o_b", "w_b"))

    Outbox(store, {}, emit=lambda _: None, clock=lambda: NOW, world_id="w_a").dispatch_due()  # no adapter: fails

    assert store.get("o_a")["state"] == "failed" and store.get("o_b")["state"] == "queued"


def test_FR_AGT_11_abandon_fails_an_unsent_entry_and_refuses_a_live_or_settled_one():
    store = InMemoryOutboxStore()
    outbox = Outbox(store, {}, emit=lambda _: None, clock=lambda: NOW)
    store._insert_if_absent(_entry("o_queued", "w"))
    store._insert_if_absent(_entry("o_live", "w"))
    assert store._claim_for_sending("o_live", "h", NOW, 30)  # someone is sending it right now

    assert outbox.abandon("o_queued")["state"] == "failed"
    outbox.dispatch_due()
    assert store.get("o_queued")["state"] == "failed"  # never sent later
    for outbox_id in ("o_live", "o_queued", "o_missing"):
        try:
            outbox.abandon(outbox_id)
        except OutboxRefused:
            continue
        raise AssertionError(f"{outbox_id} was abandoned")
