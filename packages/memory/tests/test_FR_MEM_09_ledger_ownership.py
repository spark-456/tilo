"""FR-MEM-09 security fix pass: ledger ownership must not disappear before the rows it attributes.

The World entity is the production owner source, yet the same erasure deletes it and retention purges it at 90 days
while ledger rows live 365. These tests use a `world_owner` backed by a store in the same registry (not a static
dict), both registry orders, a World older than 90 days, and a replay after erasure (BQ-211).
"""

from __future__ import annotations

import pytest
from _memory_lib import NOW, FakeStore, Rec, ago, build_registry, make_event, message_for
from tilo_memory.erasure import (
    REQUIRED_STORES,
    ErasureRequest,
    erase_user,
    request_erasure,
    verify_erasure,
)
from tilo_memory.ledger import (
    BigQueryLedgerTable,
    EventLedger,
    InMemoryLedgerTable,
    InMemoryOwnerIndex,
    LedgerRetentionStore,
)
from tilo_memory.retention import purge_expired, retention_days

ALICE, BOB = "u_alice", "u_bob"
FIRESTORE, LEDGER = "firestore", "bigquery_ledger"


class Setup:
    def __init__(self, *, use_index: bool, ledger_first: bool, world_age_days: float = 1):
        self.firestore = FakeStore()
        for world, owner in (("w_alice_1", ALICE), ("w_bob_1", BOB)):
            self.firestore.add(Rec("world", world, ago(world_age_days), owner))
        self.world_owner = lambda w: next(
            (r.user_id for r in self.firestore.records() if r.entity == "world" and r.record_id == w), None
        )
        self.table = InMemoryLedgerTable()
        self.index = InMemoryOwnerIndex() if use_index else None
        self.ledger = (
            EventLedger(self.table, world_owner=self.world_owner, owner_index=self.index)
            if use_index
            else EventLedger(self.table)
        )
        n = 0
        for world in ("w_alice_1", "w_bob_1"):
            for seq in (1, 2):
                n += 1
                self.ledger.ingest(message_for(make_event(seq, world=world, uid=n), f"m-{n}"))
        self.store = LedgerRetentionStore(self.table, world_owner=self.world_owner, owner_index=self.index)
        others = [n for n in sorted(REQUIRED_STORES) if n != LEDGER]
        order = [LEDGER, *others] if ledger_first else [*others, LEDGER]
        self.registry = {}
        for name in order:
            self.registry[name] = {FIRESTORE: self.firestore, LEDGER: self.store}.get(name, FakeStore())

    def erase(self):
        return erase_user(self.registry, request_erasure(ALICE, requested_at=NOW), now=NOW)

    def alice_rows(self):
        return [r for r in self.table.rows() if r["world_id"] == "w_alice_1"]


@pytest.mark.parametrize("use_index", [True, False])
@pytest.mark.parametrize("ledger_first", [True, False])
def test_FR_MEM_09_ledger_rows_are_erased_whatever_the_registry_order(use_index, ledger_first):
    """Owned ids are collected from every store before any delete, so deleting the World record first (firestore
    ahead of the ledger) cannot hide the ledger rows. SECURITY: Bob's rows stay."""
    s = Setup(use_index=use_index, ledger_first=ledger_first)
    report = s.erase()
    assert report.complete is True and report.removed[LEDGER] == 2
    assert s.alice_rows() == []
    assert len([r for r in s.table.rows() if r["world_id"] == "w_bob_1"]) == 2
    assert verify_erasure(s.registry, ALICE).ok is True


@pytest.mark.parametrize("ledger_first", [True, False])
def test_FR_MEM_09_a_replay_after_erasure_is_caught_even_though_the_world_is_gone(ledger_first):
    s = Setup(use_index=True, ledger_first=ledger_first)
    s.erase()
    assert [r for r in s.firestore.records() if r.record_id == "w_alice_1"] == []  # the World entity is gone
    s.ledger.ingest(message_for(make_event(1, world="w_alice_1", uid=1), "late-replay"))
    assert s.alice_rows() != []
    result = verify_erasure(s.registry, ALICE)
    assert result.ok is False and result.remaining[LEDGER] == 1
    assert s.erase().complete is True  # a re-run finishes the job
    assert verify_erasure(s.registry, ALICE).ok is True


def test_FR_MEM_09_ledger_rows_stay_attributed_after_the_world_is_purged_at_90_days():
    s = Setup(use_index=True, ledger_first=False, world_age_days=100)
    assert retention_days("world") == 90
    purge_expired({FIRESTORE: s.firestore}, now=NOW)
    assert list(s.firestore.records()) == []  # the World entity aged out; the ledger rows are 365-day data
    assert {r.user_id for r in s.store.records()} == {ALICE, BOB}
    assert s.erase().removed[LEDGER] == 2
    assert s.alice_rows() == []
    assert verify_erasure(s.registry, ALICE).ok is True


def test_FR_MEM_09_released_bindings_are_dropped_only_for_the_named_user():
    s = Setup(use_index=True, ledger_first=True)
    s.erase()
    assert verify_erasure(s.registry, ALICE).ok is True
    assert s.index.release(ALICE) == 1
    assert s.index.owner_of("w_alice_1") is None and s.index.owner_of("w_bob_1") == BOB


def test_FR_MEM_09_the_first_owner_bound_to_a_world_wins():
    index = InMemoryOwnerIndex()
    index.bind("w_x", ALICE)
    index.bind("w_x", BOB)
    assert index.owner_of("w_x") == ALICE


def test_FR_MEM_09_owner_resolver_and_index_come_together_and_junk_owners_are_not_bound():
    with pytest.raises(ValueError):
        EventLedger(InMemoryLedgerTable(), world_owner=lambda w: ALICE)
    with pytest.raises(ValueError):
        EventLedger(InMemoryLedgerTable(), owner_index=InMemoryOwnerIndex())
    index = InMemoryOwnerIndex()
    ledger = EventLedger(InMemoryLedgerTable(), world_owner=lambda w: "*", owner_index=index)
    ledger.ingest(message_for(make_event(1, world="w_x"), "m-1"))
    assert index.owner_of("w_x") is None


def test_FR_MEM_09_a_failing_owner_lookup_at_ingest_raises_so_the_message_is_redelivered():
    def broken(world_id):
        raise OSError("world store down")

    table = InMemoryLedgerTable()
    ledger = EventLedger(table, world_owner=broken, owner_index=InMemoryOwnerIndex())
    with pytest.raises(OSError):
        ledger.ingest(message_for(make_event(1), "m-1"))
    assert table.rows() == []


def test_FR_MEM_09_collection_happens_before_any_delete():
    """With three stores, no delete may run before every store has been read."""
    events: list[str] = []

    class Spy(FakeStore):
        def __init__(self, name):
            super().__init__([Rec("run", f"{name}-1", ago(1), ALICE)])
            self.name = name

        def records(self):
            events.append(f"read:{self.name}")
            return super().records()

        def delete(self, record_id):
            events.append(f"delete:{self.name}")
            super().delete(record_id)

    registry = {name: Spy(name) for name in sorted(REQUIRED_STORES)}
    erase_user(registry, request_erasure(ALICE, requested_at=NOW), now=NOW)
    first_delete = next(i for i, e in enumerate(events) if e.startswith("delete"))
    assert [e for e in events[:first_delete] if e.startswith("read")] == [f"read:{n}" for n in sorted(REQUIRED_STORES)]


def test_FR_MEM_09_a_str_subclass_user_id_is_refused():
    class Sneaky(str):
        def __eq__(self, other):
            return True

        __hash__ = str.__hash__

    with pytest.raises(ValueError):
        request_erasure(Sneaky("u_alice"), requested_at=NOW)


def test_FR_MEM_09_a_naive_requested_at_set_after_construction_fails_before_any_delete():
    registry = build_registry(sorted(REQUIRED_STORES))
    for store in registry.values():
        store.add(Rec("run", "a", ago(1), ALICE))
    request = request_erasure(ALICE, requested_at=NOW)
    object.__setattr__(request, "requested_at", NOW.replace(tzinfo=None))
    with pytest.raises(ValueError):
        erase_user(registry, request, now=NOW)
    assert all(s.delete_calls == [] and s.ids() == {"a"} for s in registry.values())
    assert isinstance(request, ErasureRequest)


def test_FR_MEM_09_an_out_of_range_timestamp_does_not_stop_the_purge():
    table = InMemoryLedgerTable()
    odd = make_event(1, world="w_x", uid=1)
    odd["ts"] = "0001-01-01T00:00:00+01:00"
    ledger = EventLedger(table)
    ledger.ingest(message_for(odd, "m-1"))
    ledger.ingest(message_for(make_event(2, world="w_x", uid=2, ts=ago(400)), "m-2"))
    store = LedgerRetentionStore(table, world_owner=lambda w: None)
    assert purge_expired({LEDGER: store}, now=NOW) == {LEDGER: 1}
    assert [r["seq"] for r in table.rows()] == [1]


def test_FR_MEM_09_ledger_delete_is_scoped_by_id_and_world():
    table = InMemoryLedgerTable()
    EventLedger(table).ingest(message_for(make_event(1, world="w_a", uid=1), "m-1"))
    table.delete_row(make_event(1, uid=1)["id"], "w_other")
    assert len(table.rows()) == 1
    table.delete_row(make_event(1, uid=1)["id"], "w_a")
    assert table.rows() == []


def test_FR_MEM_09_ledger_store_delete_of_an_unread_or_missing_id_is_a_quiet_no_op():
    table = InMemoryLedgerTable()
    EventLedger(table).ingest(message_for(make_event(1, world="w_a", uid=1), "m-1"))
    store = LedgerRetentionStore(table, world_owner=lambda w: None)
    store.delete("no-such-id")
    assert len(table.rows()) == 1
    store.delete(make_event(1, uid=1)["id"])  # records() was never called: the world is looked up
    assert table.rows() == []


def test_FR_MEM_09_table_id_with_a_trailing_newline_is_refused():
    with pytest.raises(ValueError):
        BigQueryLedgerTable(object(), "proj.ds.events\n")  # type: ignore[arg-type]


def test_FR_MEM_09_unknown_entity_error_does_not_echo_the_entity():
    with pytest.raises(ValueError) as excinfo:
        retention_days("x" * 5000)
    assert len(str(excinfo.value)) < 100
