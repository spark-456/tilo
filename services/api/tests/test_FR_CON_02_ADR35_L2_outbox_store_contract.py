"""FR-CON-02 / ADR-0035 L2 (LC-11, LC-12): one contract suite over `InMemoryOutboxStore` and `FirestoreOutboxStore`.

The Firestore store runs against `_adr35_l2_fake.OccFirestore` (a faithful fake: real `Transaction` machinery, commit
aborts if a document read changed, equality queries). The emulator was not started for this ticket (BQ-ADR35-L2-1).
Every mutator is checked on both stores; the tests after the contract are the Firestore store's own: keys, the
single-document transaction rule, the lease race, a restart, ids.
"""

from __future__ import annotations

import copy
import hashlib
import threading

import pytest
from _adr35_l2_lib import T0, WORLD_A, WORLD_B, Rig, alert, entry, outbox_id, transfer

KINDS = ["memory", "firestore"]


@pytest.fixture(params=KINDS)
def rig(request) -> Rig:
    return Rig(request.param)


@pytest.fixture
def fs() -> Rig:
    return Rig("firestore")


# --- the contract, both stores --------------------------------------------------------------------------------------


def test_FR_CON_02_ADR35_L2_insert_is_create_only_by_id_and_by_key_and_reads_are_copies(rig: Rig) -> None:
    store = rig.make()
    first = entry(1)
    assert store._insert_if_absent(copy.deepcopy(first)) is True
    assert store._insert_if_absent(copy.deepcopy(first)) is False, "the same id"
    assert store._insert_if_absent(entry(2, key=first["idempotency_key"])) is False, "the same key in the same world"
    assert store._insert_if_absent(entry(3, world=WORLD_B, key=first["idempotency_key"])) is True, "another world"
    got = store.get(first["id"])
    assert got == first
    got["state"] = "failed"
    assert store.get(first["id"])["state"] == "queued", "a read is a copy"
    assert store.get_by_idempotency_key(WORLD_A, first["idempotency_key"])["id"] == first["id"]
    assert store.get_by_idempotency_key(WORLD_B, "no-such-key") is None
    assert store.get(None) is None and store.get(outbox_id(99)) is None
    assert sorted(e["id"] for e in store.all_entries()) == [outbox_id(1), outbox_id(3)]


def test_FR_CON_02_ADR35_L2_revoke_blocks_the_key_for_good_and_cancels_only_a_scheduled_entry(rig: Rig) -> None:
    store = rig.make()
    rig.put(store, entry(1, undo=60), entry(2))
    cancelled = store._revoke(WORLD_A, entry(1)["idempotency_key"])
    assert cancelled["state"] == "cancelled"
    assert store._revoke(WORLD_A, entry(2)["idempotency_key"])["state"] == "queued", "only scheduled is cancelled"
    assert store._revoke(WORLD_A, "never-seen") is None
    assert store._insert_if_absent(entry(7, key="never-seen")) is False, "a revoked key is never created"
    assert store._revoke(WORLD_A, "never-seen") is None, "again: still nothing, still refused"
    assert store._insert_if_absent(entry(8, key="never-seen")) is False
    assert store.get(outbox_id(7)) is None


def test_FR_CON_02_ADR35_L2_cancel_takes_a_scheduled_entry_only(rig: Rig) -> None:
    store = rig.make()
    rig.put(store, entry(1, undo=60), entry(2))
    assert store._cancel(outbox_id(2)) is None
    assert store._cancel(outbox_id(99)) is None
    assert store._cancel(outbox_id(1))["state"] == "cancelled"
    assert store._cancel(outbox_id(1)) is None


def test_FR_CON_02_ADR35_L2_claim_is_exclusive_until_the_lease_expires_then_a_second_holder_takes_over(
    rig: Rig,
) -> None:
    store = rig.make()
    rig.put(store, entry(1))
    claimed = rig.claim(store, 1, "a")
    assert claimed["state"] == "sending"
    assert rig.claim(rig.make(), 1, "b") is None, "a live lease keeps the second holder out"
    rig.clock.advance(29)
    assert rig.claim(rig.make(), 1, "b") is None
    rig.clock.advance(1.5)  # 30.5 s: the lease ran out
    assert rig.claim(rig.make(), 1, "b")["state"] == "sending", "the expired lease is taken over"
    assert store._finalize_claim(outbox_id(1), "a", "sent") is None, "the old holder no longer finalizes"
    assert store._finalize_claim(outbox_id(1), "b", "sent")["state"] == "sent"
    assert rig.claim(store, 1, "c") is None, "a sent entry is not claimed"


def test_FR_CON_02_ADR35_L2_claim_waits_for_scheduled_at_plus_skew_and_for_the_retry_not_before(rig: Rig) -> None:
    store = rig.make()
    rig.put(store, entry(1, undo=60))
    assert rig.claim(store, 1, "a") is None, "inside the undo window"
    rig.clock.advance(60)
    assert rig.claim(store, 1, "a", skew=5) is None, "PI-12: not before scheduled_at + skew"
    rig.clock.advance(5)
    assert rig.claim(store, 1, "a", skew=5)["state"] == "sending"
    store._defer(outbox_id(1), "a", 1, rig.clock(), 120)
    assert rig.claim(store, 1, "b", skew=5) is None, "the retry's not_before holds it"
    rig.clock.advance(121)
    assert rig.claim(store, 1, "b", skew=5)["state"] == "sending"


def test_FR_CON_02_ADR35_L2_the_store_clock_beats_the_callers_now(rig: Rig) -> None:
    store = rig.make()
    rig.put(store, entry(1))
    assert store._claim_for_sending(outbox_id(1), "a", "2999-01-01T00:00:00.000Z", 30, 0) is not None
    assert store._claim_for_sending(outbox_id(1), "b", "2999-02-01T00:00:00.000Z", 30, 0) is None, "our clock rules"


def test_FR_CON_02_ADR35_L2_defer_records_retry_state_releases_the_lease_and_alerts_once(rig: Rig) -> None:
    store = rig.make()
    rig.put(store, entry(1))
    assert store.retry_state(outbox_id(1)) == {"attempts": 0, "not_before": "", "since": None, "ambiguous": False}
    rig.claim(store, 1, "a")
    store._defer(outbox_id(1), "intruder", 3, rig.clock(), 10)
    assert store.retry_state(outbox_id(1))["attempts"] == 0, "only the holder defers"
    store._defer(outbox_id(1), "a", 1, rig.clock(), 10, ambiguous=True, alert=alert(1))
    state = store.retry_state(outbox_id(1))
    assert state == {"attempts": 1, "not_before": "2026-10-09T10:00:10.000Z", "since": T0, "ambiguous": True}
    assert store._pending_alerts_of(None) == [(outbox_id(1), alert(1))]
    rig.clock.advance(11)
    rig.claim(store, 1, "b")
    store._defer(outbox_id(1), "b", 2, rig.clock(), 10, ambiguous=True, alert=alert(1))
    assert store.retry_state(outbox_id(1))["since"] == T0, "since is the first failure"
    store._discard_pending_alert(outbox_id(1))
    assert store._pending_alerts_of(None) == []
    rig.clock.advance(11)
    rig.claim(store, 1, "c")
    store._defer(outbox_id(1), "c", 3, rig.clock(), 10, ambiguous=True, alert=alert(1))
    assert store._pending_alerts_of(None) == [], "alerted once: never raised again for the same entry"


def test_FR_CON_02_ADR35_L2_finalize_needs_the_holder_and_writes_the_transfer_with_the_state(rig: Rig) -> None:
    store = rig.make()
    rig.put(store, entry(1), entry(2))
    assert store._finalize_claim(outbox_id(1), "a", "sent") is None, "not sending, not held"
    rig.claim(store, 1, "a")
    assert store._finalize_claim(outbox_id(1), "b", "sent", transfer(1)) is None
    done = store._finalize_claim(outbox_id(1), "a", "sent", transfer(1))
    assert done["state"] == "sent"
    claim = store._claim_oldest_pending_transfer("t1", rig.clock(), 30)
    assert claim == (outbox_id(1), WORLD_A, transfer(1)), "PI-17: the transfer was written with the state"
    rig.claim(store, 2, "a")
    failed = store._finalize_claim(outbox_id(2), "a", "failed", alert=alert(2))
    assert failed["state"] == "failed"
    assert store._pending_alerts_of(WORLD_A) == [(outbox_id(2), alert(2))]
    assert store._pending_alerts_of(WORLD_B) == []
    assert store.retry_state(outbox_id(2))["attempts"] == 0, "a final state clears the retry state"


def test_FR_CON_02_ADR35_L2_abandon_refuses_a_live_lease_and_a_settled_entry(rig: Rig) -> None:
    store = rig.make()
    rig.put(store, entry(1), entry(2), entry(3))
    rig.claim(store, 1, "a")
    assert store._abandon(outbox_id(1), rig.clock()) is None, "a live lease may be sending it"
    rig.clock.advance(31)
    assert store._abandon(outbox_id(1), rig.clock())["state"] == "failed"
    assert store._abandon(outbox_id(1), rig.clock()) is None, "already failed"
    assert store._abandon(outbox_id(2), rig.clock())["state"] == "failed", "unsent, no lease"
    assert store._abandon(outbox_id(99), rig.clock()) is None


def test_FR_CON_02_ADR35_L2_release_lease_frees_the_send_lease_for_its_holder_only(rig: Rig) -> None:
    store = rig.make()
    rig.put(store, entry(1))
    rig.claim(store, 1, "a")
    store._release_lease("send", outbox_id(1), "b")
    assert rig.claim(store, 1, "c") is None
    store._release_lease("send", outbox_id(1), "a")
    assert rig.claim(store, 1, "c")["state"] == "sending"


def _sent_with_transfer(rig: Rig, store, n: int, world: str) -> None:
    rig.put(store, entry(n, world=world))
    rig.claim(store, n, "x")
    store._finalize_claim(outbox_id(n), "x", "sent", transfer(n, world))
    rig.clock.advance(0.01)


def test_FR_CON_02_ADR35_L2_pending_transfers_go_oldest_first_one_per_world_and_leases_exclude(rig: Rig) -> None:
    store = rig.make()
    for n, world in [(1, WORLD_A), (2, WORLD_B), (3, WORLD_A)]:
        _sent_with_transfer(rig, store, n, world)
    now = rig.clock()
    first = store._claim_oldest_pending_transfer("h1", now, 30)
    assert first[:2] == (outbox_id(1), WORLD_A), "the oldest"
    second = store._claim_oldest_pending_transfer("h2", now, 30)
    assert second[:2] == (outbox_id(2), WORLD_B), "a world's later transfer waits for its earlier one"
    assert store._claim_oldest_pending_transfer("h3", now, 30) is None
    store._release_lease("transfer", outbox_id(1), "h1")
    assert store._claim_oldest_pending_transfer("h3", now, 30, only=WORLD_B) is None, "B's is leased by h2"
    again = store._claim_oldest_pending_transfer("h3", now, 30, exclude=frozenset({WORLD_B}), only=WORLD_A)
    assert again[:2] == (outbox_id(1), WORLD_A)
    first[2]["data"]["outbox_id"] = "mutated"
    store._discard_pending_transfer(outbox_id(1), "h3")
    store._discard_pending_transfer(outbox_id(2), "h2")
    third = store._claim_oldest_pending_transfer("h5", now, 30)
    assert third[:2] == (outbox_id(3), WORLD_A), "delivered ones are gone; the next of the world is next"
    assert third[2] == transfer(3), "a claim is a copy: the earlier mutation changed nothing"


def test_FR_CON_02_ADR35_L2_the_real_outbox_sends_once_over_either_store_and_a_second_instance_finds_nothing(
    rig: Rig,
) -> None:
    from tilo_connectors import Outbox
    from tilo_connectors.fakes import FakeGmail

    gmail, emitted = FakeGmail(), []
    store = rig.make()
    rig.put(store, entry(1))
    box = Outbox(store, {"gmail": gmail}, emit=emitted.append, clock=rig.clock)
    assert [e["state"] for e in box.dispatch_due()] == ["sent"]
    other = Outbox(rig.make(), {"gmail": FakeGmail()}, emit=emitted.append, clock=rig.clock)
    assert other.dispatch_due() == [], "the other instance's tick has nothing due"
    assert len(gmail.sent) == 1
    assert [t["data"]["outbox_id"] for t in emitted] == [outbox_id(1)], "one data.transfer, flushed once"


# --- the Firestore store's own rules --------------------------------------------------------------------------------


def _key_path(world: str, key: str) -> str:
    return f"outbox_keys/{world}/keys/{hashlib.sha256(key.encode()).hexdigest()}"


def test_FR_CON_02_ADR35_L2_the_key_document_is_create_only_hashed_and_written_in_the_inserts_commit(fs: Rig) -> None:
    store = fs.make()
    e = entry(1)
    fs.put(store, e)
    assert fs.db.committed_batches == [[f"outbox/{e['id']}", _key_path(WORLD_A, e["idempotency_key"])]], "one commit"
    raw = fs.db.raw(_key_path(WORLD_A, e["idempotency_key"]))
    assert raw == {"outbox_id": e["id"], "revoked": False}
    assert e["idempotency_key"] not in str(fs.db.docs.keys()), "the key text is never in a path"
    assert store._insert_if_absent(entry(2, key=e["idempotency_key"])) is False
    assert fs.db.raw(f"outbox/{outbox_id(2)}") is None, "a refused insert writes nothing"
    store._revoke(WORLD_A, "kk")
    assert fs.db.raw(_key_path(WORLD_A, "kk")) == {"outbox_id": None, "revoked": True}, "revoked, never pruned"
    ops = [kind for kind, path in fs.db.attempted_ops if path == _key_path(WORLD_A, e["idempotency_key"])]
    assert ops == ["create"], "the key document is only ever created"


def test_FR_CON_02_ADR35_L2_one_entry_one_document_and_every_mutator_is_one_transaction(fs: Rig) -> None:
    store = fs.make()
    fs.put(store, entry(1), entry(2, undo=60), entry(3))
    doc = fs.db.raw(f"outbox/{outbox_id(1)}")
    assert set(doc) == {
        "entry", "world_id", "enqueued_at", "send_lease", "transfer_lease", "retry", "transfer", "transfer_pending",
        "alert", "alert_pending", "alerted",
    }  # fmt: skip
    assert doc["entry"] == entry(1) and doc["transfer_pending"] is False and doc["enqueued_at"] == T0
    calls = [
        lambda: fs.claim(store, 1, "a"),
        lambda: store._defer(outbox_id(1), "a", 1, fs.clock(), 5, True, alert(1)),
        lambda: fs.clock.advance(6),
        lambda: fs.claim(store, 1, "b"),
        lambda: store._finalize_claim(outbox_id(1), "b", "sent", transfer(1), alert(1)),
        lambda: store._claim_oldest_pending_transfer("t", fs.clock(), 30),
        lambda: store._release_lease("transfer", outbox_id(1), "t"),
        lambda: store._discard_pending_transfer(outbox_id(1), "t"),
        lambda: store._discard_pending_alert(outbox_id(1)),
        lambda: store._cancel(outbox_id(2)),
        lambda: store._abandon(outbox_id(3), fs.clock()),
        lambda: store._revoke(WORLD_A, "fresh-key"),
    ]
    for call in calls:
        before = len(fs.db.committed_batches)
        call()
        for batch in fs.db.committed_batches[before:]:
            assert len([p for p in batch if p.startswith("outbox/")]) <= 1, "never two entries in one commit"
            assert len(batch) <= 1, f"one document per mutator: {batch}"
        assert len(fs.db.committed_batches) - before <= 1, "one transaction, not several writes"


def test_FR_CON_02_ADR35_L2_two_instances_racing_for_one_entry_only_one_claim_wins(fs: Rig) -> None:
    fs.put(fs.make(), *[entry(n) for n in range(1, 6)])
    for n in range(1, 6):
        stores, wins, gate = [fs.make() for _ in range(8)], [], threading.Barrier(8)

        def go(i: int, store=None) -> None:
            gate.wait()
            got = store._claim_for_sending(outbox_id(n), f"holder-{i}", fs.clock(), 30, 0)
            if got is not None:
                wins.append(i)

        threads = [threading.Thread(target=go, args=(i, s)) for i, s in enumerate(stores)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        assert len(wins) == 1, f"entry {n}: {wins}"


def test_FR_CON_02_ADR35_L2_a_new_instance_still_sees_the_ambiguous_retry_state_the_lease_and_the_alert(
    fs: Rig,
) -> None:
    first = fs.make()
    fs.put(first, entry(1))
    fs.claim(first, 1, "dead-instance")
    first._defer(outbox_id(1), "dead-instance", 4, fs.clock(), 90, ambiguous=True, alert=alert(1))
    reborn = fs.make()
    state = reborn.retry_state(outbox_id(1))
    assert state["ambiguous"] is True and state["attempts"] == 4 and state["not_before"] == "2026-10-09T10:01:30.000Z"
    assert reborn._pending_alerts_of(None) == [(outbox_id(1), alert(1))]
    assert fs.claim(reborn, 1, "new") is None, "not_before holds across the restart"
    fs.clock.advance(91)
    assert fs.claim(reborn, 1, "new")["state"] == "sending"
    assert reborn.retry_state(outbox_id(1))["ambiguous"] is True, "ambiguous stays ambiguous; it is never failed"
    assert reborn.get(outbox_id(1))["state"] == "sending"


def test_FR_CON_02_ADR35_L2_a_dead_holders_lease_expires_and_a_second_instance_claims_it(fs: Rig) -> None:
    dead, alive = fs.make(), fs.make()
    fs.put(dead, entry(1))
    fs.claim(dead, 1, "dead")  # the instance dies here: nothing releases or finalizes
    assert fs.claim(alive, 1, "alive") is None
    fs.clock.advance(31)
    assert fs.claim(alive, 1, "alive")["state"] == "sending"
    assert dead._finalize_claim(outbox_id(1), "dead", "sent") is None


@pytest.mark.parametrize("bad", ["../outbox/x", "a/b", "", "x" * 600, "01jb5vq0000000000000000001", "W_a", None, 7])
def test_FR_CON_02_ADR35_L2_ids_are_matched_against_the_schema_before_any_path_is_built(fs: Rig, bad) -> None:
    store = fs.make()
    fs.put(store, entry(1))
    touched = len(fs.db.touched)
    assert store.get(bad) is None
    assert store._cancel(bad) is None and store._abandon(bad, fs.clock()) is None
    assert store._claim_for_sending(bad, "h", fs.clock(), 30, 0) is None
    assert store._finalize_claim(bad, "h", "sent") is None
    assert store.retry_state(bad)["attempts"] == 0
    store._defer(bad, "h", 1, fs.clock(), 1)
    store._release_lease("send", bad, "h")
    store._discard_pending_alert(bad)
    store._discard_pending_transfer(bad, "h")
    assert store.get_by_idempotency_key(bad, "k") is None
    assert store._revoke(bad, "k") is None
    assert fs.db.touched[touched:] == [], "no path was built from it"
    with pytest.raises(ValueError):
        store._insert_if_absent({**entry(2), "id": bad})
    with pytest.raises(ValueError):
        store._insert_if_absent({**entry(3), "world_id": bad})
    assert fs.db.touched[touched:] == []


class _Boom:
    """A client whose every call raises with text that must never reach a caller."""

    TEXT = "SECRET-grpc-detail-7f3a"

    def __getattr__(self, name):
        def fail(*args, **kwargs):
            raise RuntimeError(self.TEXT)

        return fail


def test_FR_CON_02_ADR35_L2_a_failing_firestore_is_a_fixed_503_with_no_entry_and_no_exception_text(fs: Rig) -> None:
    from fastapi import HTTPException
    from tilo_api.outbox_firestore import FirestoreOutboxStore

    store = FirestoreOutboxStore(_Boom(), clock=fs.clock)
    calls = [
        lambda: store._insert_if_absent(entry(1)),
        lambda: store.get(outbox_id(1)),
        lambda: store.all_entries(),
        lambda: store.get_by_idempotency_key(WORLD_A, "k"),
        lambda: store._claim_for_sending(outbox_id(1), "h", fs.clock(), 30, 0),
        lambda: store._claim_oldest_pending_transfer("h", fs.clock(), 30),
    ]
    for call in calls:
        with pytest.raises(HTTPException) as caught:
            call()
        assert caught.value.status_code == 503 and caught.value.detail == "outbox_unavailable"
        assert _Boom.TEXT not in repr(caught.value) and caught.value.__cause__ is None


def test_FR_CON_02_ADR35_L2_the_schema_patterns_the_store_matches_are_the_contracts_own() -> None:
    import json
    import pathlib

    from tilo_api import outbox_firestore as mod

    common = json.loads((pathlib.Path(__file__).parents[3] / "contracts" / "common.schema.json").read_text("utf-8"))
    defs = common["$defs"]
    assert mod.ID_PATTERN.pattern == defs["ulid"]["pattern"].strip("^$")
    assert mod.WORLD_PATTERN.pattern == defs["world_id"]["pattern"].strip("^$")
