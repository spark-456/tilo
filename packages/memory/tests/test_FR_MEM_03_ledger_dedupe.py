"""FR-MEM-03: "Event ledger in BigQuery with deduplication". Acceptance: "Replayed Pub/Sub messages produce no
duplicate rows" (PRD 13.5). Also PRD 13.2 (Event ledger: every TiloEvent, BigQuery, append-only, "Deduplicated by
`id`"), 15.3 and 22.2 D-11 (Pub/Sub to BigQuery ledger, "Ordering, replay, analytics").

`tilo_memory` does not exist yet, so every test here fails at import until the builder lands it. In-memory fakes
only: `InMemoryLedgerTable` stands for the BigQuery `tilo_ledger.events` table (API_FR_MEM_03_09.md).
"""

from __future__ import annotations

import json
import threading

import pytest
from _memory_lib import (
    REQUIRED_COLUMNS,
    FakePubSubMessage,
    all_fixture_events,
    as_json,
    make_event,
    message_for,
)
from hypothesis import given, settings
from hypothesis import strategies as st
from tilo_memory.ledger import EventLedger, InMemoryLedgerTable

settings.register_profile("memory", deadline=None)
settings.load_profile("memory")


@pytest.fixture
def table():
    return InMemoryLedgerTable()


@pytest.fixture
def ledger(table):
    return EventLedger(table)


def ids(rows) -> list[str]:
    return [r["id"] for r in rows]


def test_FR_MEM_03_fixture_ids_are_unique():
    """Guard for the tests below: the registered-type fixtures can be replayed as one stream."""
    events = all_fixture_events()
    assert len(events) == 72
    assert len({e["id"] for e in events}) == len(events)


def test_FR_MEM_03_first_delivery_inserts_one_row(ledger, table):
    event = make_event(1)
    result = ledger.ingest(message_for(event, "m-1"))
    assert result.status == "inserted"
    assert result.event_id == event["id"]
    rows = table.rows()
    assert len(rows) == 1
    assert rows[0]["id"] == event["id"]
    assert rows[0]["type"] == "memory.hit"
    assert rows[0]["seq"] == 1
    assert rows[0]["world_id"] == "w_alpha"
    assert as_json(rows[0]["data"]) == event["data"]


def test_FR_MEM_03_redelivered_message_produces_no_duplicate_row(ledger, table):
    """Pub/Sub is at-least-once: the same message (same message id) can arrive again."""
    event = make_event(1)
    first = ledger.ingest(message_for(event, "m-1"))
    for _ in range(5):
        again = ledger.ingest(message_for(event, "m-1"))
        assert again.status == "duplicate"
        assert again.event_id == event["id"]
    assert first.status == "inserted"
    assert ids(table.rows()) == [event["id"]]


def test_FR_MEM_03_replay_with_new_message_id_is_still_a_duplicate(ledger, table):
    """The key is the event `id` (PRD 13.2), not the broker's message id: a republished event gets a new one."""
    event = make_event(1)
    ledger.ingest(message_for(event, "m-1"))
    result = ledger.ingest(message_for(event, "m-999"))
    assert result.status == "duplicate"
    assert len(table.rows()) == 1


def test_FR_MEM_03_replay_of_a_whole_stream_adds_no_rows(ledger, table):
    stream = all_fixture_events()
    for i, event in enumerate(stream):
        assert ledger.ingest(message_for(event, f"first-{i}")).status == "inserted"
    assert len(table.rows()) == 72
    for i, event in enumerate(stream):
        assert ledger.ingest(message_for(event, f"replay-{i}")).status == "duplicate"
    assert sorted(ids(table.rows())) == sorted(e["id"] for e in stream)


def test_FR_MEM_03_dedupe_holds_across_ledger_instances_on_one_table(table):
    """Two subscriber instances (Cloud Run scales out) share one table; neither may insert a second copy."""
    a, b = EventLedger(table), EventLedger(table)
    event = make_event(1)
    assert a.ingest(message_for(event, "m-1")).status == "inserted"
    assert b.ingest(message_for(event, "m-2")).status == "duplicate"
    assert len(table.rows()) == 1


def test_FR_MEM_03_concurrent_redelivery_inserts_each_event_once(table):
    events = [make_event(n) for n in range(1, 21)]
    barrier = threading.Barrier(8)
    errors: list[BaseException] = []

    def worker(k: int) -> None:
        subscriber = EventLedger(table)
        try:
            barrier.wait()
            for event in events:
                subscriber.ingest(message_for(event, f"t{k}-{event['seq']}"))
        except BaseException as exc:  # noqa: BLE001 - surfaced by the assertion below
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(k,)) for k in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert sorted(ids(table.rows())) == sorted(e["id"] for e in events)


def test_FR_MEM_03_replay_with_different_content_never_rewrites_the_row(ledger, table):
    """Append-only (PRD 13.2): a second message with the same id but other content does not overwrite the first."""
    original = make_event(1)
    forged = make_event(1)
    forged["summary"] = "Rewritten after the fact."
    forged["data"]["origin_cost"] = 600
    forged["data"]["saved"] = 599.5
    ledger.ingest(message_for(original, "m-1"))
    result = ledger.ingest(message_for(forged, "m-2"))
    assert result.status in ("duplicate", "conflict")  # BQ-194: which one is the builder's choice
    rows = table.rows()
    assert len(rows) == 1
    assert rows[0]["summary"] == original["summary"]
    assert as_json(rows[0]["data"]) == original["data"]


def test_FR_MEM_03_ledger_has_no_way_to_change_or_remove_a_row():
    """Append-only: the public ledger offers ingest and reads, nothing that updates or deletes."""
    forbidden = ("update", "delete", "remove", "truncate", "upsert", "overwrite", "replace", "clear", "pop")
    public = [n for n in dir(EventLedger) if not n.startswith("_")]
    assert "ingest" in public
    assert [n for n in public if any(word in n.lower() for word in forbidden)] == []


def test_FR_MEM_03_events_come_back_deduplicated_and_in_seq_order(ledger):
    events = [make_event(n) for n in (3, 1, 2)] + [
        make_event(1, world="w_beta", uid=101),
        make_event(2, world="w_beta", uid=102),
    ]
    for i, event in enumerate(events + events):  # every event twice
        ledger.ingest(message_for(event, f"m-{i}"))
    alpha = ledger.events("w_alpha")
    assert [e["seq"] for e in alpha] == [1, 2, 3]
    assert alpha == sorted([e for e in events if e["world_id"] == "w_alpha"], key=lambda e: e["seq"])
    assert [e["id"] for e in ledger.events("w_beta")] == [events[3]["id"], events[4]["id"]]
    assert len(ledger.events()) == 5
    assert ledger.count() == 5


@pytest.mark.parametrize("column", REQUIRED_COLUMNS)
def test_FR_MEM_03_event_missing_a_required_column_is_rejected(ledger, table, column):
    broken = make_event(1)
    del broken[column]
    result = ledger.ingest(message_for(broken, "m-bad"))
    assert result.status == "rejected"
    assert table.rows() == []
    # A poison message does not stop the stream: the next valid one is stored.
    assert ledger.ingest(message_for(make_event(2), "m-ok")).status == "inserted"
    assert len(table.rows()) == 1


@pytest.mark.parametrize("payload", [b"", b"not json", b"[]", b'"x"', b"null", b'{"type": "memory.hit"}'])
def test_FR_MEM_03_unreadable_payload_is_rejected_and_stores_nothing(ledger, table, payload):
    result = ledger.ingest(FakePubSubMessage(data=payload, message_id="m-bad"))
    assert result.status == "rejected"
    assert result.event_id is None
    assert table.rows() == []


def test_FR_MEM_03_rejection_does_not_echo_the_payload(ledger):
    secret_marker = "SENTINEL-" + "x" * 12
    event = make_event(1)
    event["summary"] = secret_marker
    del event["id"]
    result = ledger.ingest(message_for(event, "m-bad"))
    assert result.status == "rejected"
    assert secret_marker not in repr(result)
    assert secret_marker not in json.dumps(getattr(result, "__dict__", {}), default=str)


@given(
    order=st.permutations(range(6)),
    extra=st.lists(st.integers(min_value=0, max_value=5), max_size=25),
    extras_first=st.booleans(),
)
def test_FR_MEM_03_property_any_delivery_order_with_repeats_gives_exactly_the_unique_events(order, extra, extras_first):
    """Invariant: rows == unique event ids, whatever the order and however many times each one is delivered."""
    table = InMemoryLedgerTable()
    ledger = EventLedger(table)
    events = [make_event(n + 1) for n in range(6)]
    deliveries = [*extra, *order] if extras_first else [*order, *extra]
    for i, idx in enumerate(deliveries):
        ledger.ingest(message_for(events[idx], f"m-{i}"))
    assert sorted(ids(table.rows())) == sorted(e["id"] for e in events)
    assert [e["seq"] for e in ledger.events("w_alpha")] == [1, 2, 3, 4, 5, 6]
