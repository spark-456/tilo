"""EV-15 in `EventValidator` / `WorldWriter` (contracts/event.rules.md, ADR-0018 section 4 and T1 notes; FR-AGT-02 T3).

Artifact events name versions the world recorded:
- an `artifact.created` names version 1 of an `artifact_id` the world has not recorded (no second created);
- an `artifact.reviewed` or `artifact.delivered` names a version that an earlier `artifact.created`,
  `artifact.versioned`
  or `artifact.rolled_back` of the same world recorded, same `artifact_id`;
- an `artifact.versioned` (`previous_version`) or `artifact.rolled_back` (`restored_version`) continues a recorded
  version and records the next one (the highest recorded plus 1, AR-02).
So no stamp, parcel, version badge or rewind shows for a version never created (HR-1).

The streams are the contracts' own fixtures (T1): `fixtures/streams/artifact-versions.jsonl` is valid and each
`fixtures/streams/invalid/ev15_*.jsonl` breaks only EV-15. They go through a real `WorldWriter` (the single writer), so
a rejected event writes nothing (D-11). The property test compares the writer with a small oracle of the rule.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import CONTRACTS_DIR, make_memory_writer
from hypothesis import HealthCheck, Phase, given, settings
from hypothesis import strategies as st
from tilo_harness.validator import EventRejected

STREAMS = CONTRACTS_DIR / "fixtures" / "streams"
LAYOUT = CONTRACTS_DIR / "fixtures" / "layout" / "valid" / "village_basic.json"


def _events(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _writer():
    layout = json.loads(LAYOUT.read_text(encoding="utf-8"))
    return make_memory_writer(layout, world_id="w_village_basic", run_id="r_village_basic_2")


# invalid stream -> the seq of the event EV-15 refuses (every earlier event is fine)
INVALID = {
    "ev15_created_names_version_2": 1,
    "ev15_created_twice": 2,
    "ev15_delivered_before_created": 1,
    "ev15_delivered_other_artifact": 2,
    "ev15_reviewed_version_never_recorded": 2,
    "ev15_rolled_back_onto_a_recorded_version": 3,
    "ev15_rolled_back_restored_never_recorded": 2,
    "ev15_versioned_previous_never_recorded": 2,
    "ev15_versioned_skips_a_version": 2,
}


def test_EV_15_the_contract_s_valid_artifact_stream_appends_cleanly() -> None:
    writer, store = _writer()
    stream = _events(STREAMS / "artifact-versions.jsonl")
    for event in stream:
        assert writer.append(event)["id"] == event["id"]
    assert [e["type"] for e in store.read_events("org_demo", "w_village_basic")] == [
        "artifact.created",
        "artifact.versioned",
        "artifact.rolled_back",
        "artifact.reviewed",
        "artifact.delivered",
    ]


def test_EV_15_every_invalid_fixture_stream_is_listed_here() -> None:
    on_disk = {p.stem for p in (STREAMS / "invalid").glob("ev15_*.jsonl")}
    assert on_disk == set(INVALID), "a new EV-15 fixture needs an expected seq here"


@pytest.mark.parametrize(("name", "refused_seq"), sorted(INVALID.items()))
def test_EV_15_an_event_naming_a_version_the_world_never_recorded_is_refused_and_writes_nothing(
    name, refused_seq
) -> None:
    writer, store = _writer()
    stream = _events(STREAMS / "invalid" / f"{name}.jsonl")
    for event in stream:
        if event["seq"] < refused_seq:
            writer.append(event)
            continue
        with pytest.raises(EventRejected) as excinfo:
            writer.append(event)
        assert excinfo.value.problems and all(p.startswith("EV-15") for p in excinfo.value.problems), (
            f"{name}: only EV-15 breaks, got {excinfo.value.problems}"
        )
        break
    written = store.read_events("org_demo", "w_village_basic")
    assert [e["seq"] for e in written] == list(range(1, refused_seq)), "D-11: the refused event is not written"


def test_EV_15_created_names_version_1_of_an_unrecorded_id_through_emit() -> None:
    writer, _store = _writer()
    kwargs = {
        "type": "artifact.created",
        "actor": "A_s1",
        "target": "art_x1",
        "level": "L1",
        "district": "D1",
        "summary": "The agent made an item.",
        "data": {"artifact": {"artifact_id": "art_x1", "version": 1}},
    }
    assert writer.emit(**kwargs)["seq"] == 1
    with pytest.raises(EventRejected) as excinfo:
        writer.emit(**kwargs)  # the same id again: a second created of a recorded id
    assert any(p.startswith("EV-15") for p in excinfo.value.problems), excinfo.value.problems


def test_EV_15_the_record_survives_a_writer_takeover() -> None:
    """A new writer over the same store rebuilds what the world recorded from the stream (WorldWriter.open)."""
    from tilo_harness.writer import WorldWriter

    first, store = _writer()
    stream = _events(STREAMS / "artifact-versions.jsonl")
    first.append(stream[0])  # created v1
    first.append(stream[1])  # versioned v2
    first.close()

    layout = json.loads(LAYOUT.read_text(encoding="utf-8"))
    second = WorldWriter(
        store, org_id="org_demo", world_id="w_village_basic", run_id="r_village_basic_2", layout=layout, writer_id="w2"
    )
    second.open()
    with pytest.raises(EventRejected) as excinfo:
        second.append({**stream[0], "id": "01JB5VQ0000000000000000299", "seq": 3})  # created again: already recorded
    assert any(p.startswith("EV-15") for p in excinfo.value.problems), excinfo.value.problems
    assert second.append(stream[2])["seq"] == 3, "rolled_back restores v1 as v3: v2 was recorded before the takeover"


def test_EV_15_another_world_s_artifacts_do_not_count() -> None:
    """`of the same world`: version 1 recorded in one world does not let another world name a later version."""
    writer_a, _ = _writer()
    stream = _events(STREAMS / "artifact-versions.jsonl")
    writer_a.append(stream[0])
    layout = json.loads(LAYOUT.read_text(encoding="utf-8"))
    writer_b, _ = make_memory_writer(layout, world_id="w_other_world", run_id="r_other_1")
    stray = {**stream[1], "world_id": "w_other_world", "seq": 1, "cause": None}
    with pytest.raises(EventRejected) as excinfo:
        writer_b.append(stray)  # versioned v2 of an id this world never created
    assert any(p.startswith("EV-15") for p in excinfo.value.problems), excinfo.value.problems


# --- property: the writer accepts exactly what the rule says ----------------------------------------

NO_SHRINK = (Phase.explicit, Phase.reuse, Phase.generate)  # a writer per example is slow: report, do not shrink
ART = ("art_p0", "art_p1", "art_p2")
KINDS = ("created", "versioned", "rolled_back", "reviewed", "delivered")
ACTORS = {"created": "A_s1", "versioned": "A_s1", "rolled_back": "u_owner", "reviewed": "A_v1", "delivered": "A_l1"}


def _kwargs(kind: str, art: str, a: int, b: int) -> dict:
    ref = {"artifact_id": art, "version": b}
    data = {
        "created": {"artifact": ref},
        "versioned": {"artifact": ref, "previous_version": a},
        "rolled_back": {"artifact": ref, "restored_version": a},
        "reviewed": {"artifact": ref, "result": "passed"},
        "delivered": {"artifact": ref, "format": "in_app", "outbox_id": None},
    }[kind]
    return {
        "type": f"artifact.{kind}",
        "actor": ACTORS[kind],
        "target": art,
        "level": "L1",
        "district": "D1",
        "summary": f"{kind} {art}",
        "data": data,
    }


def _oracle(kind: str, top: int, a: int, b: int) -> bool:
    if kind == "created":
        return b == 1 and top == 0
    if kind in ("versioned", "rolled_back"):
        return 1 <= a <= top and b == top + 1
    return 1 <= b <= top


@settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture], phases=NO_SHRINK)
@given(
    steps=st.lists(
        st.tuples(st.sampled_from(KINDS), st.sampled_from(ART), st.integers(1, 4), st.integers(1, 4)), max_size=14
    )
)
def test_EV_15_property_the_writer_accepts_an_artifact_event_exactly_when_the_rule_does(steps) -> None:
    writer, store = _writer()
    latest: dict[str, int] = {}
    accepted = 0
    for kind, art, a, b in steps:
        top = latest.get(art, 0)
        expected = _oracle(kind, top, a, b)
        try:
            writer.emit(**_kwargs(kind, art, a, b))
            took = True
        except EventRejected as rejected:
            took = False
            assert any(p.startswith("EV-15") for p in rejected.problems), rejected.problems
        assert took == expected, (kind, art, a, b, top)
        if took:
            accepted += 1
            if kind in ("created", "versioned", "rolled_back"):
                latest[art] = b
    events = store.read_events("org_demo", "w_village_basic")
    assert len(events) == accepted and [e["seq"] for e in events] == list(range(1, accepted + 1))
    for art in ART:  # versions of an id run 1, 2, 3 with no gaps (AR-02)
        recorded = [
            e["data"]["artifact"]["version"]
            for e in events
            if e["type"] in ("artifact.created", "artifact.versioned", "artifact.rolled_back")
            and e["data"]["artifact"]["artifact_id"] == art
        ]
        assert recorded == list(range(1, len(recorded) + 1)), (art, recorded)
