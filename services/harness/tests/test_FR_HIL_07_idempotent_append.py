"""FR-HIL-07 (github.com/spark-456/tilo#46, S0 decision, no contract change): the idempotency
key is the event's existing required ULID `id` (contracts/event.schema.json) -- EV-10 already
refuses a reused id. This SH ticket is the harness writer's half: `WorldWriter.append` gets a
retried event whose `id` is already committed in this world. If its content is byte-identical to
the committed event, `append` must return the committed event (idempotent success) -- no new
seq, nothing written to the store or any view, head unchanged -- instead of raising
`EventRejected`. The same id with any *different* content (another field, `seq`, `data`, or a
nested value) must still raise `EventRejected`, exactly as it does today.

This must hold for a resend of an event built and committed via `append()` (the dispatcher's
replay path, issue #46 item 1), for a resend of an event committed via `emit()`, and after a
takeover: a second `WorldWriter` that `open()`s the world later (having read the committed event
back from the store into its own `WorldState`) must treat a re-send of that same event the same
way, with no special-casing of which writer instance first committed it.

Uses `MemoryStore` only (see conftest.py's `make_memory_writer`); no emulator.
"""

from __future__ import annotations

import copy

import pytest
from conftest import FakeClock, make_memory_writer, world_requested_kwargs
from tilo_harness.writer import EventRejected, WorldWriter

_NULL_TRACE = {
    "model_role": None,
    "profile": None,
    "tokens_in": None,
    "tokens_out": None,
    "tool": None,
    "latency_ms": None,
    "archive_ref": None,
}


def _event(seq: int, event_id: str, *, cause: str | None = None) -> dict:
    """A schema-valid, fully-built `world.requested` event ready for `append()` -- same shape
    `WorldWriter.emit()` would have produced, so a caller (a dispatcher retrying a part, or a
    test) can resend it unchanged."""
    return {
        "v": "1.0",
        "id": event_id,
        "seq": seq,
        "ts": "2026-09-29T09:30:00.000Z",
        "world_id": "w_village_basic",
        "run_id": "r_test_1",
        "level": None,
        "district": None,
        "item": None,
        "severity": "info",
        "credits": 0,
        "cause": cause,
        "vis": "all",
        "authz": None,
        "trace": dict(_NULL_TRACE),
        **world_requested_kwargs(),
    }


@pytest.fixture
def writer_and_store(village_basic_layout: dict):
    return make_memory_writer(village_basic_layout)


def test_FR_HIL_07_append_same_id_same_content_is_idempotent(writer_and_store) -> None:
    writer, store = writer_and_store
    event = _event(1, "01JB5VQ0000000000000FH0701")

    committed = writer.append(event)
    head_before = store.read_head("org_demo", "w_village_basic")

    # A fresh dict, not the same Python object and not the writer's own return value, so this
    # proves value equality is what makes it idempotent, not object identity.
    resent = writer.append(copy.deepcopy(event))

    assert resent == committed, "FR-HIL-07: a resend of the identical event must return the committed event"
    assert store.read_events("org_demo", "w_village_basic") == [committed], (
        "FR-HIL-07: an idempotent append must not write a second copy to the stream"
    )
    assert store.read_view("org_demo", "w_village_basic", "shared") == [dict(committed, seq=1)], (
        "FR-HIL-07: an idempotent append must not write a second copy to any view either"
    )
    assert store.read_head("org_demo", "w_village_basic") == head_before, (
        "FR-HIL-07: an idempotent append must leave last_seq, view_seq and the lease unchanged"
    )

    # No seq was consumed by the replay: the next real append still lands at seq 2.
    following = writer.append(_event(2, "01JB5VQ0000000000000FH0702", cause=committed["id"]))
    assert following["seq"] == 2


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda e: {**e, "summary": "A different summary."}, id="different_field"),
        pytest.param(lambda e: {**e, "seq": 2}, id="different_seq"),
        pytest.param(lambda e: {**e, "data": {**e["data"], "title": "A different title"}}, id="different_data"),
        pytest.param(
            lambda e: {**e, "trace": {**e["trace"], "tokens_in": 5}},
            id="different_nested_value",
        ),
    ],
)
def test_FR_HIL_07_append_same_id_different_content_raises_EventRejected(writer_and_store, mutate) -> None:
    writer, store = writer_and_store
    original = _event(1, "01JB5VQ0000000000000FH0710")
    writer.append(original)

    retried = mutate(copy.deepcopy(original))
    # seq is the one field the mutation itself does not change for the "different_seq" case above
    # (it *is* the change); every other case keeps the original seq so id collision, not a seq
    # gap, is what append must reject on.
    with pytest.raises(EventRejected):
        writer.append(retried)

    assert store.read_events("org_demo", "w_village_basic") == [original], (
        "FR-HIL-07: an id reused with different content must still write nothing"
    )


def test_FR_HIL_07_resend_of_an_emitted_event_is_idempotent(writer_and_store) -> None:
    writer, store = writer_and_store
    emitted = writer.emit(**world_requested_kwargs())
    head_before = store.read_head("org_demo", "w_village_basic")

    resent = writer.append(copy.deepcopy(emitted))

    assert resent == emitted, "FR-HIL-07: resending an emit()-produced event must be idempotent too"
    assert store.read_events("org_demo", "w_village_basic") == [emitted]
    assert store.read_head("org_demo", "w_village_basic") == head_before


def test_FR_HIL_07_idempotent_result_survives_a_takeover(village_basic_layout: dict, fake_clock: FakeClock) -> None:
    from tilo_harness.store import MemoryStore

    store = MemoryStore()

    def make(writer_id: str) -> WorldWriter:
        return WorldWriter(
            store,
            org_id="org_demo",
            world_id="w_village_basic",
            run_id="r_test_1",
            layout=village_basic_layout,
            writer_id=writer_id,
            lease_s=30.0,
            clock=fake_clock,
        )

    writer1 = make("writer_1")
    writer1.open()
    committed = writer1.append(_event(1, "01JB5VQ0000000000000FH0720"))
    # writer1 "crashes" here without ever seeing its own write acknowledged by the caller, so the
    # caller (e.g. a dispatcher) retries the same event -- but only after a second writer has
    # since taken the world over.

    fake_clock.advance(31.0)  # past writer1's 30s lease
    writer2 = make("writer_2")
    writer2.open()  # takes over; loads `committed` back from the store into its own WorldState
    head_before = store.read_head("org_demo", "w_village_basic")

    resent = writer2.append(copy.deepcopy(committed))

    assert resent == committed, "FR-HIL-07: a takeover writer must give the same idempotent result for a re-send"
    assert store.read_events("org_demo", "w_village_basic") == [committed]
    assert store.read_head("org_demo", "w_village_basic") == head_before, (
        "FR-HIL-07: the idempotent replay must not consume a seq or touch the lease, even across a takeover"
    )
