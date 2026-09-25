"""D-11 (contracts/event.rules.md, PRD 9.3 "summary: string", "data: type-specific payload"):
a string that cannot round-trip through UTF-8 -- e.g. a lone UTF-16 surrogate, the kind produced
by `json.loads('"a\\ud800"')` -- must never reach a store. `EventValidator.problems()` reports
it as a problem starting "schema" wherever it sits in the event (summary, a `data` string
value, a `data` key, or the nested `item.label`), and `WorldWriter.emit`/`.append` raise
`EventRejected` before either `MemoryStore` or `FirestoreStore` sees it: nothing is stored and
the world's head (next `seq`) does not move. A valid non-ASCII string (accented Latin, CJK, an
emoji) is unaffected -- this is a UTF-8-round-trip check, not an ASCII-only rule.

Resolved ambiguity (CLAUDE.md "apply the PRD's stated default" -- ticket brief asks for a data
KEY case specifically): every schema under contracts/events/data/ is `additionalProperties:
false` with a fixed, closed set of key names (confirmed by reading every file in that
directory), so there is no registered type whose `data` accepts an arbitrary key name to inject
a bad key into without *also* tripping `additionalProperties`/`required`. The data-key case
below (`test_D_11_utf8_surrogate_in_data_key_is_a_schema_problem`) therefore still pins the
required, user-visible outcome -- `problems()` reports a "schema" problem for that event -- but
cannot, given the closed contracts, prove in isolation that a dedicated UTF-8 check (rather than
the incidental additionalProperties violation) is what fired. Logged here and in the
test-writer report rather than inventing a free-form schema field that does not exist in
contracts/.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import make_memory_writer

# 'a' followed by one unpaired UTF-16 high surrogate (U+D800). json.loads happily decodes a bare
# \uXXXX escape without checking surrogate pairing, so this reproduces exactly the kind of string
# a model or a malformed upstream payload could hand the harness. It cannot be encoded to UTF-8.
LONE_SURROGATE = json.loads('"a\\ud800"')

VALID_NON_ASCII = "Café 東京 🚀"


def test_D_11_utf8_fixture_lone_surrogate_does_not_round_trip() -> None:
    """Sanity check on the fixture itself, not on tilo_harness: proves LONE_SURROGATE is in fact
    not UTF-8-encodable, so the tests below are exercising the right kind of string."""
    with pytest.raises(UnicodeEncodeError):
        LONE_SURROGATE.encode("utf-8")


def test_D_11_utf8_fixture_valid_non_ascii_does_round_trip() -> None:
    assert VALID_NON_ASCII.encode("utf-8").decode("utf-8") == VALID_NON_ASCII


# ---------------------------------------------------------------------------
# EventValidator.problems() -- one event-shaped dict per injection point
# ---------------------------------------------------------------------------


def _full_event(**overrides) -> dict:
    event: dict = {
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
    event.update(overrides)
    return event


@pytest.fixture(scope="module")
def validator(repo_root: Path):
    from tilo_harness.validator import EventValidator

    return EventValidator.from_repo(repo_root)


def test_D_11_utf8_surrogate_in_summary_is_a_schema_problem(validator) -> None:
    event = _full_event(summary="A" + LONE_SURROGATE)
    problems = validator.problems(event)
    assert any(p.startswith("schema") for p in problems), (
        f"D-11: a summary with a non-UTF-8-round-trippable string must fail with a 'schema' problem, got {problems}"
    )


def test_D_11_utf8_surrogate_in_data_string_value_is_a_schema_problem(validator) -> None:
    event = _full_event(data={"title": "x" + LONE_SURROGATE, "channel": "web", "destination": None})
    problems = validator.problems(event)
    assert any(p.startswith("schema") for p in problems), (
        f"D-11: a data string value with a non-UTF-8-round-trippable string must fail with a "
        f"'schema' problem, got {problems}"
    )


def test_D_11_utf8_surrogate_in_data_key_is_a_schema_problem(validator) -> None:
    """See the module docstring's resolved ambiguity: contracts/events/data/world.requested's
    additionalProperties: false means any extra key also trips that rule, so this event fails
    both, but the required outcome -- a 'schema' problem -- still holds either way."""
    data = {
        "title": "Do some work",
        "channel": "web",
        "destination": None,
        "k" + LONE_SURROGATE: "extra",
    }
    event = _full_event(data=data)
    problems = validator.problems(event)
    assert any(p.startswith("schema") for p in problems), (
        f"D-11: a data key with a non-UTF-8-round-trippable string must fail with a 'schema' problem, got {problems}"
    )


def test_D_11_utf8_surrogate_in_nested_item_label_is_a_schema_problem(validator) -> None:
    event = _full_event(item={"kind": "document", "artifact_id": None, "label": "x" + LONE_SURROGATE})
    problems = validator.problems(event)
    assert any(p.startswith("schema") for p in problems), (
        f"D-11: item.label with a non-UTF-8-round-trippable string must fail with a 'schema' problem, got {problems}"
    )


def test_D_11_utf8_valid_non_ascii_string_is_accepted(validator) -> None:
    event = _full_event(
        summary="Café 東京 🚀 asked Tilo to do some work.",
        item={"kind": "document", "artifact_id": None, "label": VALID_NON_ASCII},
    )
    assert validator.problems(event) == [], (
        "D-11: a valid non-ASCII string must not be rejected -- not an ASCII-only rule"
    )


# ---------------------------------------------------------------------------
# WorldWriter.emit / .append over MemoryStore -- EventRejected, nothing stored, head unchanged
# ---------------------------------------------------------------------------


def test_D_11_emit_rejects_utf8_surrogate_in_summary_memory(village_basic_layout: dict) -> None:
    from tilo_harness.writer import EventRejected

    writer, store = make_memory_writer(village_basic_layout, world_id="w_utf8_emit_summary")
    with pytest.raises(EventRejected) as excinfo:
        writer.emit(
            type="world.requested",
            actor="u_owner",
            target="w_utf8_emit_summary",
            summary="A" + LONE_SURROGATE,
            data={"title": "Do some work", "channel": "web", "destination": None},
        )
    assert any(p.startswith("schema") for p in excinfo.value.problems), excinfo.value.problems
    assert store.read_events("org_demo", "w_utf8_emit_summary") == [], "D-11: a rejected emit must write nothing"
    assert store.read_view("org_demo", "w_utf8_emit_summary", "shared") == []

    # head unchanged: the very next emit must still land at seq 1, not 2
    resumed = writer.emit(
        type="world.requested",
        actor="u_owner",
        target="w_utf8_emit_summary",
        summary="You asked Tilo to do some work.",
        data={"title": "Do some work", "channel": "web", "destination": None},
    )
    assert resumed["seq"] == 1, "D-11: a rejected emit must not advance the head/seq"


def test_D_11_emit_rejects_utf8_surrogate_in_item_label_memory(village_basic_layout: dict) -> None:
    from tilo_harness.writer import EventRejected

    writer, store = make_memory_writer(village_basic_layout, world_id="w_utf8_emit_item")
    with pytest.raises(EventRejected) as excinfo:
        writer.emit(
            type="world.requested",
            actor="u_owner",
            target="w_utf8_emit_item",
            summary="You asked Tilo to do some work.",
            data={"title": "Do some work", "channel": "web", "destination": None},
            item={"kind": "document", "artifact_id": None, "label": "x" + LONE_SURROGATE},
        )
    assert any(p.startswith("schema") for p in excinfo.value.problems), excinfo.value.problems
    assert store.read_events("org_demo", "w_utf8_emit_item") == []


def test_D_11_append_rejects_utf8_surrogate_memory(village_basic_layout: dict) -> None:
    from tilo_harness.writer import EventRejected

    writer, store = make_memory_writer(village_basic_layout, world_id="w_utf8_append")
    bad_event = _full_event(
        id="01JB5VQ0000000000000009101",
        world_id="w_utf8_append",
        data={"title": "x" + LONE_SURROGATE, "channel": "web", "destination": None},
    )
    with pytest.raises(EventRejected) as excinfo:
        writer.append(bad_event)
    assert any(p.startswith("schema") for p in excinfo.value.problems), excinfo.value.problems
    assert store.read_events("org_demo", "w_utf8_append") == [], "D-11: a rejected append must write nothing"

    # head unchanged: seq 1 is still free, a valid append at seq=1 must succeed
    good_event = _full_event(id="01JB5VQ0000000000000009102", world_id="w_utf8_append", seq=1)
    accepted = writer.append(good_event)
    assert accepted["seq"] == 1, "D-11: a rejected append must not consume seq 1"


def test_D_11_emit_accepts_valid_non_ascii_summary_memory(village_basic_layout: dict) -> None:
    """A valid non-ASCII summary is stored unchanged end to end -- proves this is a UTF-8
    round-trip check, not a reject-everything-non-ASCII rule."""
    writer, store = make_memory_writer(village_basic_layout, world_id="w_utf8_valid")
    event = writer.emit(
        type="world.requested",
        actor="u_owner",
        target="w_utf8_valid",
        summary="Café 東京 🚀 asked Tilo to do some work.",
        data={"title": "Do some work", "channel": "web", "destination": None},
    )
    stored = store.read_events("org_demo", "w_utf8_valid")
    assert stored[0]["summary"] == "Café 東京 🚀 asked Tilo to do some work."
    assert event["seq"] == 1


# ---------------------------------------------------------------------------
# Same behaviour over FirestoreStore (emulator): EV-01 / D-11 parity per conftest's module
# docstring ("FirestoreStore: same read/write semantics as MemoryStore per the public API").
# ---------------------------------------------------------------------------


@pytest.mark.emulator
def test_D_11_emit_rejects_utf8_surrogate_in_summary_firestore(emulator_host: str, village_basic_layout: dict) -> None:
    from tilo_harness.store import FirestoreStore
    from tilo_harness.writer import EventRejected, WorldWriter

    store = FirestoreStore(project_id="demo-tilo")
    writer = WorldWriter(
        store,
        org_id="org_demo",
        world_id="w_utf8_fs_summary",
        run_id="r_utf8_fs_1",
        layout=village_basic_layout,
        writer_id="writer_1",
        lease_s=30.0,
    )
    writer.open()

    with pytest.raises(EventRejected) as excinfo:
        writer.emit(
            type="world.requested",
            actor="u_owner",
            target="w_utf8_fs_summary",
            summary="A" + LONE_SURROGATE,
            data={"title": "Do some work", "channel": "web", "destination": None},
        )
    assert any(p.startswith("schema") for p in excinfo.value.problems), excinfo.value.problems
    assert store.read_events("org_demo", "w_utf8_fs_summary") == [], (
        "D-11: FirestoreStore must behave the same as MemoryStore -- a rejected emit writes nothing"
    )
    assert store.read_view("org_demo", "w_utf8_fs_summary", "shared") == []

    resumed = writer.emit(
        type="world.requested",
        actor="u_owner",
        target="w_utf8_fs_summary",
        summary="You asked Tilo to do some work.",
        data={"title": "Do some work", "channel": "web", "destination": None},
    )
    assert resumed["seq"] == 1, "D-11: a rejected emit must not advance the head/seq on FirestoreStore either"


@pytest.mark.emulator
def test_D_11_append_rejects_utf8_surrogate_firestore(emulator_host: str, village_basic_layout: dict) -> None:
    from tilo_harness.store import FirestoreStore
    from tilo_harness.writer import EventRejected, WorldWriter

    store = FirestoreStore(project_id="demo-tilo")
    writer = WorldWriter(
        store,
        org_id="org_demo",
        world_id="w_utf8_fs_append",
        run_id="r_utf8_fs_2",
        layout=village_basic_layout,
        writer_id="writer_1",
        lease_s=30.0,
    )
    writer.open()

    bad_event = _full_event(
        id="01JB5VQ0000000000000009201",
        world_id="w_utf8_fs_append",
        data={"title": "x" + LONE_SURROGATE, "channel": "web", "destination": None},
    )
    with pytest.raises(EventRejected) as excinfo:
        writer.append(bad_event)
    assert any(p.startswith("schema") for p in excinfo.value.problems), excinfo.value.problems
    assert store.read_events("org_demo", "w_utf8_fs_append") == []

    good_event = _full_event(id="01JB5VQ0000000000000009202", world_id="w_utf8_fs_append", seq=1)
    accepted = writer.append(good_event)
    assert accepted["seq"] == 1, "D-11: a rejected append must not consume seq 1 on FirestoreStore either"


# ---------------------------------------------------------------------------
# The rejection itself must be printable: a problem message never carries the bad text
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "where",
    ["top_level_key", "data_key", "data_key_with_nan_value"],
)
def test_D_11_utf8_problem_messages_round_trip_for_a_bad_key(validator, village_basic_layout: dict, where) -> None:
    from tilo_harness.writer import EventRejected

    bad_key = "k" + LONE_SURROGATE
    event = _full_event()
    if where == "top_level_key":
        event[bad_key] = "x"
    elif where == "data_key":
        event["data"] = {**event["data"], bad_key: "extra"}
    else:
        event["data"] = {**event["data"], bad_key: float("nan")}

    problems = validator.problems(event)
    assert problems and all(p.startswith("schema") for p in problems), problems
    "; ".join(problems).encode("utf-8")  # raises UnicodeEncodeError if a message carries the raw key

    writer, store = make_memory_writer(village_basic_layout, world_id="w_village_basic")
    with pytest.raises(EventRejected) as excinfo:
        writer.append(event)
    str(excinfo.value).encode("utf-8")
    "; ".join(excinfo.value.problems).encode("utf-8")
    assert store.read_events("org_demo", "w_village_basic") == []
