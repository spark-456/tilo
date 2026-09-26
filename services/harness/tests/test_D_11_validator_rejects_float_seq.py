"""D-11, P0-09 fix round 4 -- qa-breaker: a `seq` that is a Python `float` with an integer value,
like `2.0`, got past validation. `jsonschema`'s Draft 2020-12 "integer" type checker is spec-
correct but too loose for this harness: it accepts any JSON number with a zero fractional part,
including a Python `float` (`jsonschema._types`: `is_integer(checker, instance) or
isinstance(instance, float) and instance.is_integer()`). `EventValidator._stream_problems`'s
EV-10 check (`event["seq"] != state.last_seq + 1`) then also let it through, since `2.0 == 2` in
Python. The two stores disagreed on the result: `MemoryStore.append` accepted `seq: 2.0` and
`read_events` returned it unchanged (a `float` seq in the stream), while `FirestoreStore.append`
raised a raw `ValueError` ("Unknown format code 'd' for float") out of
`f"{event['seq']:08d}"` instead of `EventRejected` -- not the "single writer" the ticket brief
promises, and not the same failure on every store.

`EventValidator` now validates every "integer"-typed field (`event.schema.json`'s `seq`, and
every "integer" field inside `events/data/*.schema.json`) against a stricter `jsonschema` type
checker that requires a real Python `int` (see `validator._is_strict_python_int`), so a float
seq is rejected with a "schema: ..." problem before `_stream_problems` (EV-10) or any store call
ever runs -- both stores now behave identically: `EventRejected`, nothing written.

Also pins the ticket brief's public API: `EventRejected` lives at `tilo_harness.validator` (it
was defined only in `writer.py`, so `from tilo_harness.validator import EventRejected` raised
`ImportError`); `tilo_harness.writer.EventRejected` still works too, and is the same class
object, for any caller written against that path.
"""

from __future__ import annotations

import copy

import pytest
from conftest import make_memory_writer


def test_D_11_EventRejected_is_importable_from_validator_and_is_the_writer_one_too() -> None:
    from tilo_harness.validator import EventRejected as validator_EventRejected
    from tilo_harness.writer import EventRejected as writer_EventRejected

    assert validator_EventRejected is writer_EventRejected


def test_D_11_validator_rejects_a_float_seq_with_integer_value() -> None:
    from tilo_harness.validator import EventValidator

    validator = EventValidator.from_repo()
    event = {
        "v": "1.0",
        "id": "01JB5VQ0000000000000009101",
        "seq": 2.0,
        "ts": "2026-09-29T09:30:00.000Z",
        "world_id": "w_village_basic",
        "run_id": "r_test_1",
        "type": "world.requested",
        "actor": "u_owner",
        "target": "w_village_basic",
        "level": None,
        "district": None,
        "item": None,
        "severity": "info",
        "credits": 0,
        "summary": "You asked Tilo to do some work.",
        "cause": None,
        "vis": "all",
        "authz": None,
        "data": {"title": "Do some work", "channel": "web", "destination": None},
        "trace": {
            "model_role": None,
            "profile": None,
            "tokens_in": None,
            "tokens_out": None,
            "tool": None,
            "latency_ms": None,
            "archive_ref": None,
        },
    }
    problems = validator.problems(event)
    assert problems, "D-11: seq=2.0 must be rejected but the validator found no problem"
    assert any(p.startswith("schema") and "seq" in p for p in problems), problems


def test_D_11_memory_store_append_rejects_a_float_seq_and_writes_nothing(
    village_basic_layout: dict, village_basic_stream: list[dict]
) -> None:
    """qa-breaker's exact repro: open a WorldWriter on w_village_basic with the village_basic
    layout, append(stream[0]), then append a copy of stream[1] with seq: 2.0."""
    from tilo_harness.writer import EventRejected

    writer, store = make_memory_writer(village_basic_layout)
    writer.append(village_basic_stream[0])

    bad = copy.deepcopy(village_basic_stream[1])
    bad["seq"] = 2.0

    with pytest.raises(EventRejected) as excinfo:
        writer.append(bad)
    assert any(p.startswith("schema") for p in excinfo.value.problems), excinfo.value.problems

    stored = store.read_events("org_demo", "w_village_basic")
    assert [e["seq"] for e in stored] == [1], (
        "D-11: a float seq must never reach the store, on MemoryStore or FirestoreStore alike"
    )
    assert all(isinstance(e["seq"], int) and not isinstance(e["seq"], bool) for e in stored)


@pytest.mark.emulator
def test_D_11_firestore_store_append_rejects_a_float_seq_and_writes_nothing(
    emulator_host: str, village_basic_layout: dict, village_basic_stream: list[dict]
) -> None:
    """Same repro against the real Firestore emulator: before this fix round,
    `FirestoreStore.append` raised a raw `ValueError` from `f"{event['seq']:08d}"` instead of
    `EventRejected` -- the validator must catch this before any store call, so FirestoreStore
    never sees a float seq at all."""
    from tilo_harness.store import FirestoreStore
    from tilo_harness.writer import EventRejected, WorldWriter

    # world_id must match the fixture stream's own `world_id` (EV-10): the stream's events are
    # fixed at "w_village_basic". No other @pytest.mark.emulator test writes to this world id
    # against FirestoreStore (see conftest.py/the non-emulator suite for the many MemoryStore
    # tests reusing the same id -- a separate in-process store per test, never this emulator).
    org_id, world_id, run_id = "org_demo", "w_village_basic", "r_float_seq_emulator_1"
    store = FirestoreStore(project_id="demo-tilo")
    writer = WorldWriter(
        store,
        org_id=org_id,
        world_id=world_id,
        run_id=run_id,
        layout=village_basic_layout,
        writer_id="writer_float_seq",
    )
    writer.open()
    try:
        writer.append(village_basic_stream[0])

        bad = copy.deepcopy(village_basic_stream[1])
        bad["seq"] = 2.0

        with pytest.raises(EventRejected) as excinfo:
            writer.append(bad)
        assert any(p.startswith("schema") for p in excinfo.value.problems), excinfo.value.problems

        stored = store.read_events(org_id, world_id)
        assert [e["seq"] for e in stored] == [1]
        assert all(isinstance(e["seq"], int) and not isinstance(e["seq"], bool) for e in stored)
    finally:
        writer.close()
