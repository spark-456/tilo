"""D-11 (PRD 22.2: "One writer per world; Firestore live; Pub/Sub to BigQuery ledger", 9.3
"seq: integer, strictly increasing per world"): `WorldWriter.emit`/`.append` assign and check
`seq`/`id`, reject unregistered types (EV-01) and bad data (EV-02), and never leave a partial
write behind (the ticket's "a rejected event raises EventRejected and writes nothing").

Uses `MemoryStore` throughout: same read/write semantics as `FirestoreStore` per the public API,
and does not need the emulator, so these run in the default (non-`emulator`-marked) suite.
"""

from __future__ import annotations

import pytest
from conftest import ULID_PATTERN, agent_idle_kwargs, make_memory_writer, world_requested_kwargs
from tilo_harness.writer import EventRejected


@pytest.fixture
def writer_and_store(village_basic_layout: dict):
    return make_memory_writer(village_basic_layout)


def test_D_11_emit_assigns_seq_starting_at_1_and_strictly_increasing(writer_and_store) -> None:
    writer, _store = writer_and_store
    first = writer.emit(**world_requested_kwargs())
    second = writer.emit(**agent_idle_kwargs("A_v1", "B3", level="L1", district="D1"))
    third = writer.emit(**agent_idle_kwargs("A_v1", "B3", level="L1", district="D1"))

    assert [first["seq"], second["seq"], third["seq"]] == [1, 2, 3]


def test_D_11_emit_assigns_a_valid_ulid_and_unique_ids(writer_and_store) -> None:
    writer, _store = writer_and_store
    events = [writer.emit(**world_requested_kwargs()) for _ in range(3)]

    ids = [e["id"] for e in events]
    assert all(ULID_PATTERN.match(i) for i in ids), f"D-11: emit() must assign canonical ULIDs, got {ids}"
    assert len(set(ids)) == len(ids), "D-11: emit() must assign unique ids"


def test_D_11_emit_writes_through_to_the_store_in_seq_order(writer_and_store) -> None:
    writer, store = writer_and_store
    writer.emit(**world_requested_kwargs())
    writer.emit(**agent_idle_kwargs("A_v1", "B3", level="L1", district="D1"))

    stored = store.read_events("org_demo", "w_village_basic")
    assert [e["seq"] for e in stored] == [1, 2]
    assert [e["type"] for e in stored] == ["world.requested", "agent.idle"]


def test_D_11_emit_rejects_an_unregistered_type_EV_01(writer_and_store) -> None:
    writer, store = writer_and_store
    with pytest.raises(EventRejected) as excinfo:
        writer.emit(
            type="world.exploded",
            actor="u_owner",
            target="w_village_basic",
            summary="Not a real event type.",
            data={},
        )
    assert any(p.startswith("EV-01") for p in excinfo.value.problems), excinfo.value.problems
    assert store.read_events("org_demo", "w_village_basic") == [], (
        "D-11: a rejected event must write nothing -- not the stream, not any view, not the head"
    )
    assert store.read_view("org_demo", "w_village_basic", "shared") == [], (
        "D-11: a rejected event must not appear in any view either"
    )


def test_D_11_emit_rejects_bad_data_EV_02(writer_and_store) -> None:
    writer, store = writer_and_store
    with pytest.raises(EventRejected) as excinfo:
        writer.emit(
            type="world.requested",
            actor="u_owner",
            target="w_village_basic",
            summary="Missing the required title field.",
            data={"channel": "web"},  # missing required "title"
        )
    assert any(p.startswith("EV-02") for p in excinfo.value.problems), excinfo.value.problems
    assert store.read_events("org_demo", "w_village_basic") == []


def test_D_11_a_rejected_emit_does_not_advance_seq(writer_and_store) -> None:
    writer, _store = writer_and_store
    writer.emit(**world_requested_kwargs())
    with pytest.raises(EventRejected):
        writer.emit(type="not.registered", actor="u_owner", target="w_village_basic", summary="x", data={})

    next_event = writer.emit(**agent_idle_kwargs("A_v1", "B3", level="L1", district="D1"))
    assert next_event["seq"] == 2, "D-11: a rejected emit must not consume a seq number"


def test_D_11_emit_rejects_an_actor_not_in_the_layout_EV_12(writer_and_store) -> None:
    writer, store = writer_and_store
    with pytest.raises(EventRejected) as excinfo:
        writer.emit(**agent_idle_kwargs("A_not_in_layout", "B3", level="L1", district="D1"))
    assert any(p.startswith("EV-12") for p in excinfo.value.problems), excinfo.value.problems
    assert store.read_events("org_demo", "w_village_basic") == []


# --- append(): the replay path for pre-built events (D-11, PRD 9.3) --------


def _built_event(seq: int, event_id: str, *, cause: str | None = None) -> dict:
    kwargs = world_requested_kwargs()
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
        "trace": {
            "model_role": None,
            "profile": None,
            "tokens_in": None,
            "tokens_out": None,
            "tool": None,
            "latency_ms": None,
            "archive_ref": None,
        },
        **kwargs,
    }


def test_D_11_append_accepts_seq_exactly_last_plus_one(writer_and_store) -> None:
    writer, _store = writer_and_store
    first = writer.append(_built_event(1, "01JB5VQ0000000000000000101"))
    second = writer.append(_built_event(2, "01JB5VQ0000000000000000102", cause=first["id"]))

    assert [first["seq"], second["seq"]] == [1, 2]


@pytest.mark.parametrize("bad_seq", [3, 1, 2], ids=["gap", "duplicate-of-first", "restart-not-plus-one"])
def test_D_11_append_rejects_seq_other_than_last_plus_one(writer_and_store, bad_seq: int) -> None:
    writer, store = writer_and_store
    writer.append(_built_event(1, "01JB5VQ0000000000000000201"))
    with pytest.raises(EventRejected) as excinfo:
        writer.append(_built_event(bad_seq, "01JB5VQ0000000000000000202"))
    assert any(p.startswith("EV-10") for p in excinfo.value.problems), excinfo.value.problems
    assert [e["seq"] for e in store.read_events("org_demo", "w_village_basic")] == [1]


def test_D_11_append_rejects_a_repeated_id(writer_and_store) -> None:
    writer, store = writer_and_store
    writer.append(_built_event(1, "01JB5VQ0000000000000000301"))
    with pytest.raises(EventRejected) as excinfo:
        writer.append(_built_event(2, "01JB5VQ0000000000000000301"))
    assert any("EV-10" in p or "id" in p.lower() for p in excinfo.value.problems), excinfo.value.problems
    assert [e["seq"] for e in store.read_events("org_demo", "w_village_basic")] == [1]


def test_D_11_append_rejects_an_unknown_cause_EV_11(writer_and_store) -> None:
    writer, store = writer_and_store
    with pytest.raises(EventRejected) as excinfo:
        writer.append(_built_event(1, "01JB5VQ0000000000000000401", cause="01JB5VQ0000000000000099999"))
    assert any(p.startswith("EV-11") for p in excinfo.value.problems), excinfo.value.problems
    assert store.read_events("org_demo", "w_village_basic") == []


def test_D_11_append_accepts_a_cause_that_is_an_earlier_event_of_this_world(writer_and_store) -> None:
    writer, _store = writer_and_store
    first = writer.append(_built_event(1, "01JB5VQ0000000000000000501"))
    second = writer.append(_built_event(2, "01JB5VQ0000000000000000502", cause=first["id"]))
    assert second["cause"] == first["id"]
