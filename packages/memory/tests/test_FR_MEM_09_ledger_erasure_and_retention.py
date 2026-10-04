"""FR-MEM-09 with FR-MEM-03: the BigQuery event ledger is one of "every store". PRD 13.2 calls it append-only, yet
PRD 16.5 requires account deletion to reach it and PRD 15.1 gives it a 1 year retention. `LedgerRetentionStore` is the
one sanctioned path that removes ledger rows (BQ-195): a row belongs to the user who owns its world.

`tilo_memory` does not exist yet, so these fail at import. In-memory fakes only (API_FR_MEM_03_09.md).
"""

from __future__ import annotations

from datetime import timedelta

from _memory_lib import NOW, FakeStore, Rec, ago, build_registry, make_event, message_for
from tilo_memory.erasure import REQUIRED_STORES, erase_user, request_erasure, verify_erasure
from tilo_memory.ledger import EventLedger, InMemoryLedgerTable, LedgerRetentionStore
from tilo_memory.retention import purge_expired

ALICE, BOB = "u_alice", "u_bob"
OWNERS = {"w_alice_1": ALICE, "w_alice_2": ALICE, "w_bob_1": BOB}


def seeded():
    table = InMemoryLedgerTable()
    ledger = EventLedger(table)
    n = 0
    for world in ("w_alice_1", "w_alice_2", "w_bob_1", "w_orphan"):
        for seq in (1, 2, 3):
            n += 1
            ledger.ingest(message_for(make_event(seq, world=world, uid=n), f"m-{n}"))
    store = LedgerRetentionStore(table, world_owner=OWNERS.get)
    return table, ledger, store


def registry_with_ledger(store):
    registry = build_registry(sorted(REQUIRED_STORES))
    ledger_name = next(n for n in REQUIRED_STORES if n.startswith("bigquery"))
    registry[ledger_name] = store
    return registry


def test_FR_MEM_09_ledger_store_attributes_each_row_to_the_owner_of_its_world():
    _, _, store = seeded()
    records = list(store.records())
    assert len(records) == 12
    by_user: dict = {}
    for rec in records:
        by_user[rec.user_id] = by_user.get(rec.user_id, 0) + 1
        assert rec.entity == "event_ledger"
    assert by_user == {ALICE: 6, BOB: 3, None: 3}


def test_FR_MEM_09_erasing_a_user_removes_their_ledger_rows_and_only_theirs():
    table, ledger, store = seeded()
    report = erase_user(registry_with_ledger(store), request_erasure(ALICE, requested_at=NOW), now=NOW)
    assert report.complete is True
    assert {r["world_id"] for r in table.rows()} == {"w_bob_1", "w_orphan"}
    assert len(table.rows()) == 6
    assert ledger.events("w_alice_1") == [] and ledger.events("w_alice_2") == []
    assert len(ledger.events("w_bob_1")) == 3  # SECURITY: another user's history is untouched
    assert len(ledger.events("w_orphan")) == 3  # and so are events no user owns


def test_FR_MEM_09_verification_script_passes_for_the_ledger_after_erasure():
    _, _, store = seeded()
    registry = registry_with_ledger(store)
    assert verify_erasure(registry, ALICE).ok is False
    erase_user(registry, request_erasure(ALICE, requested_at=NOW), now=NOW)
    assert verify_erasure(registry, ALICE).ok is True


def test_FR_MEM_09_a_replayed_message_cannot_bring_an_erased_users_row_back_unnoticed():
    """After erasure a redelivered Pub/Sub message re-inserts the row; the verifying script must see it."""
    table, ledger, store = seeded()
    registry = registry_with_ledger(store)
    erase_user(registry, request_erasure(ALICE, requested_at=NOW), now=NOW)
    ledger.ingest(message_for(make_event(1, world="w_alice_1"), "late-replay"))
    assert verify_erasure(registry, ALICE).ok is False


def test_FR_MEM_09_ledger_rows_past_one_year_are_purged_and_younger_rows_stay():
    table = InMemoryLedgerTable()
    ledger = EventLedger(table)
    ledger.ingest(message_for(make_event(1, world="w_alice_1", ts=ago(366)), "m-old"))
    ledger.ingest(message_for(make_event(2, world="w_alice_1", ts=ago(364)), "m-new"))
    store = LedgerRetentionStore(table, world_owner=OWNERS.get)
    removed = purge_expired({"bigquery_ledger": store}, now=NOW)
    assert removed == {"bigquery_ledger": 1}
    assert [r["seq"] for r in table.rows()] == [2]


def test_FR_MEM_09_the_ledger_store_uses_the_event_timestamp_as_its_age():
    table = InMemoryLedgerTable()
    EventLedger(table).ingest(message_for(make_event(1, world="w_alice_1", ts=NOW - timedelta(days=10)), "m-1"))
    (record,) = list(LedgerRetentionStore(table, world_owner=OWNERS.get).records())
    assert record.created_at == NOW - timedelta(days=10)
    assert record.created_at.tzinfo is not None


def test_FR_MEM_09_other_stores_in_the_registry_are_unaffected_by_the_ledger_adapter():
    """Sanity: mixing the ledger adapter with plain fakes erases both kinds."""
    _, _, store = seeded()
    registry = registry_with_ledger(store)
    other = next(n for n in registry if not n.startswith("bigquery"))
    registry[other] = FakeStore([Rec("run", "x", ago(1), ALICE), Rec("run", "y", ago(1), BOB)])
    erase_user(registry, request_erasure(ALICE, requested_at=NOW), now=NOW)
    assert registry[other].ids() == {"y"}
