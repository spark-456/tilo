"""CL-INT-2 follow-ups (#155; FR-WLD-07, FR-AGT-11): a world-scoped Outbox cannot abandon or cancel another world's
entry, and a halted Outbox (a paused world) claims nothing at the moment it would send."""

from __future__ import annotations

import pytest
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


def _outbox(store: InMemoryOutboxStore, **kwargs) -> Outbox:
    return Outbox(store, {}, emit=lambda _: None, clock=lambda: NOW, **kwargs)


@pytest.mark.parametrize("verb", ["abandon", "cancel"])
def test_FR_WLD_07_a_world_scoped_outbox_refuses_another_worlds_entry(verb):
    store = InMemoryOutboxStore()
    store._insert_if_absent(_entry("o_b", "w_b", state="scheduled"))
    scoped = _outbox(store, world_id="w_a")

    with pytest.raises(OutboxRefused):
        getattr(scoped, verb)("o_b")

    assert store.get("o_b")["state"] == "scheduled"  # untouched


def test_FR_AGT_11_a_world_scoped_outbox_still_abandons_and_cancels_its_own_entries():
    store = InMemoryOutboxStore()
    store._insert_if_absent(_entry("o_queued", "w_a"))
    store._insert_if_absent(_entry("o_sched", "w_a", state="scheduled"))
    scoped = _outbox(store, world_id="w_a")

    assert scoped.abandon("o_queued")["state"] == "failed"
    assert scoped.cancel("o_sched")["state"] == "cancelled"


def test_FR_AGT_11_an_unscoped_outbox_keeps_working_on_any_world():
    store = InMemoryOutboxStore()
    store._insert_if_absent(_entry("o_b", "w_b"))

    assert _outbox(store).abandon("o_b")["state"] == "failed"


def test_FR_WLD_07_a_halted_outbox_claims_nothing_until_the_halt_lifts():
    store, halted = InMemoryOutboxStore(), [True]
    store._insert_if_absent(_entry("o_a", "w_a"))
    outbox = _outbox(store, world_id="w_a", halted=lambda: halted[0])

    outbox.dispatch_due()
    assert store.get("o_a")["state"] == "queued"  # never claimed: no lease, no adapter lookup

    halted[0] = False
    outbox.dispatch_due()
    assert store.get("o_a")["state"] == "failed"  # no adapter is bound, so the claim fails it
