"""D-11, P0-09 fix round 2 -- qa-breaker: `jsonschema`'s `minimum: 0` on
`common.schema.json#/$defs/credits` never rejects `float("nan")` or `float("inf")` (`nan < 0` and
`inf < 0` are both `False`), so `EventValidator.problems()` returned `[]` for a `credits: NaN` or
`credits: Infinity` event and `WorldWriter` wrote it to every store. A related case: an integer
like `10**30` also passed the schema (no `maximum`), but then `FirestoreStore` raised a raw
`ValueError` instead of `EventRejected` while `MemoryStore` accepted it -- the two stores
disagreed, and "the single writer stores events that are not valid JSON" either way, since
strict `json.dumps(allow_nan=False)` (what the web client's `JSON.parse` and any strict archive
writer both require) refuses NaN/Infinity.

`problems()` now walks the whole event (data included) and rejects any non-finite float or any
integer outside int64 range, before the schema check even runs, so every store treats these
identically: `EventRejected`, nothing written.
"""

from __future__ import annotations

import pytest
from conftest import make_memory_writer, world_requested_kwargs
from tilo_harness.validator import EventValidator
from tilo_harness.writer import EventRejected


@pytest.fixture
def validator() -> EventValidator:
    return EventValidator.from_repo()


@pytest.mark.parametrize("bad_credits", [float("nan"), float("inf"), float("-inf")], ids=["nan", "inf", "-inf"])
def test_D_11_validator_rejects_non_finite_credits(validator: EventValidator, bad_credits: float) -> None:
    event = {
        "v": "1.0",
        "id": "01JB5VQ0000000000000009001",
        "seq": 1,
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
        "credits": bad_credits,
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
    assert problems, f"D-11: credits={bad_credits!r} must be rejected but the validator found no problem"
    assert all(p.startswith("schema") for p in problems), problems


def test_D_11_validator_rejects_an_integer_outside_int64_range(validator: EventValidator) -> None:
    event = {
        "v": "1.0",
        "id": "01JB5VQ0000000000000009002",
        "seq": 1,
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
        "credits": 10**30,
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
    assert problems, "D-11: credits=10**30 must be rejected but the validator found no problem"
    assert all(p.startswith("schema") for p in problems), problems


@pytest.mark.parametrize("bad_credits", [float("nan"), float("inf")], ids=["nan", "inf"])
def test_D_11_writer_emit_rejects_non_finite_credits_and_writes_nothing(village_basic_layout, bad_credits) -> None:
    writer, store = make_memory_writer(village_basic_layout)
    with pytest.raises(EventRejected) as excinfo:
        writer.emit(**world_requested_kwargs(), credits=bad_credits)
    assert all(p.startswith("schema") for p in excinfo.value.problems), excinfo.value.problems
    assert store.read_events("org_demo", "w_village_basic") == [], (
        "D-11: a non-finite credits value must be rejected before it is ever written"
    )
    assert store.read_view("org_demo", "w_village_basic", "shared") == []


def test_D_11_writer_emit_rejects_an_oversized_integer_credits_and_writes_nothing(village_basic_layout) -> None:
    """Firestore's proto rejects an int this large with a raw ValueError; MemoryStore would
    accept it -- the validator must catch it first, so both stores behave the same: EventRejected,
    nothing written, not a raw store exception."""
    writer, store = make_memory_writer(village_basic_layout)
    with pytest.raises(EventRejected) as excinfo:
        writer.emit(**world_requested_kwargs(), credits=10**30)
    assert all(p.startswith("schema") for p in excinfo.value.problems), excinfo.value.problems
    assert store.read_events("org_demo", "w_village_basic") == []
