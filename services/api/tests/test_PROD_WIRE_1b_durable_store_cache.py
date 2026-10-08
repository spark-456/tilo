"""PROD-WIRE slice 1b, ADR-0026 decisions 2 and 3: the durable write-through cache (`tilo_api.durable_store`).

The interface this pins is in `_pw1b_lib.py`'s docstring. Every test runs over `MemoryBackend` and, under
`-m emulator`, over `FirestoreBackend` on a `demo-` project (the `pw1b_rig` fixture); a "process" is a `DurableStore`
and its writer over the shared backend, so a second `rig.process()` is a restart. Today there is no
`tilo_api.durable_store`, so every file of this slice fails to import it.
"""

from __future__ import annotations

import json
import pathlib
from contextlib import contextmanager

import pytest
from _pw1b_lib import (
    OTHER,
    OWNER,
    P1,
    P3,
    T1,
    W1,
    W2,
    W3,
    FlakyWriter,
    commits_fail,
    granted,
    ids,
    make_rig,
    part,
    policy,
    requested,
    seed,
    task,
    world,
)  # fmt: skip
from fastapi import HTTPException
from hypothesis import given, settings
from hypothesis import strategies as st

VILLAGE = json.loads(
    (pathlib.Path(__file__).resolve().parents[3] / "contracts/fixtures/layout/valid/village_basic.json").read_text(
        "utf-8"
    )
)


@contextmanager
def refused(status: int, detail: str):
    with pytest.raises(HTTPException) as caught:
        yield
    assert (caught.value.status_code, caught.value.detail) == (status, detail)


def test_PROD_WIRE_1b_records_are_stored_in_the_adr_layout(pw1b_rig) -> None:
    store, _ = pw1b_rig.process()
    seed(store, worlds={W1: world()}, tasks={T1: task()}, policies={P1: policy(P1)}, policy_worlds={P1: W1})
    doc, backend = pw1b_rig.backend.read("worlds", W1), pw1b_rig.backend
    assert {
        "owner",
        "districts",
        "owner_channels",
        "run_id",
        "paused",
        "prior_world_id",
        "layout",
        "created_at",
    } <= set(doc)
    assert (doc["owner"], doc["layout"], doc["rev"]) == (OWNER, None, 1)
    stored = backend.read("tasks", T1)
    assert {
        "owner",
        "world_id",
        "draft",
        "brief",
        "questions",
        "answers",
        "approaches",
        "gaps",
        "next_seq",
        "rev",
    } <= set(stored)
    assert "lock" not in stored, "the task's lock never reaches the store"
    assert backend.read("policies", P1) == {"record": policy(P1), "world_id": W1, "rev": 1}
    assert backend.read("worlds", "w_pw1b_missing") is None


def test_PROD_WIRE_1b_a_mutation_commits_once_before_the_cache_changes(pw1b_rig) -> None:
    store, _ = pw1b_rig.process()
    seed(store, worlds={W1: world()})
    real, untouched = pw1b_rig.backend.commit, []
    pw1b_rig.backend.commit = lambda *a, **k: (
        untouched.append(store.worlds[W1].paused is False and not store.pending_events.get(W1)),
        real(*a, **k),
    )[1]
    try:
        store.commit(worlds={W1: world(paused=True)}, parts={W1: [part(1)]})
    finally:
        del pw1b_rig.backend.commit
    assert untouched == [True], "one backend transaction, and the cache still held the old values while it ran"
    assert store.worlds[W1].paused is True and store.pending_events[W1] == [part(1)]
    assert pw1b_rig.backend.read("worlds", W1)["rev"] == 2 and pw1b_rig.backend.queue(W1) == [part(1)]


@pytest.mark.parametrize("applied", [False, True], ids=["refused", "ambiguous"])
def test_PROD_WIRE_1b_a_failed_commit_changes_no_cache_evicts_and_answers_503(pw1b_rig, applied: bool) -> None:
    store, _ = pw1b_rig.process()
    seed(store, worlds={W1: world()})
    with commits_fail(pw1b_rig.backend, applied=applied), refused(503, "store_unavailable"):
        store.commit(worlds={W1: world(paused=True)}, parts={W1: [part(1)]})
    assert W1 not in store.worlds and not store.pending_events.get(W1), "the touched entries are evicted"
    assert pw1b_rig.backend.read("worlds", W1)["paused"] is applied, (
        "the record and its queue land whole, or not at all"
    )
    assert (pw1b_rig.backend.queue(W1) == [part(1)]) is applied
    assert store.load_world(W1, settle=True) == world(paused=applied), "the next access reloads what is really stored"


def test_PROD_WIRE_1b_a_rev_mismatch_is_409_stale_and_a_create_never_overwrites(pw1b_rig) -> None:
    one, _ = pw1b_rig.process()
    two, _ = pw1b_rig.process()
    seed(one, worlds={W1: world()})
    two.load_world(W1, settle=True)
    one.commit(worlds={W1: world(paused=True)})
    with refused(409, "stale"):
        two.commit(worlds={W1: world(owner_channels=("web",))})
    assert W1 not in two.worlds and tuple(pw1b_rig.backend.read("worlds", W1)["owner_channels"]) == ("web", "email")
    assert two.load_world(W1, settle=True) == world(paused=True)
    with refused(409, "stale"):
        two.commit(worlds={W1: world(owner=OTHER)}, create=[("worlds", W1)])
    assert pw1b_rig.backend.read("worlds", W1)["owner"] == OWNER


def test_PROD_WIRE_1b_a_missing_document_is_not_cached_and_a_bad_id_never_reaches_the_backend(pw1b_rig) -> None:
    one, _ = pw1b_rig.process()
    two, _ = pw1b_rig.process()
    assert one.load_world(W1, settle=True) is None and one.load_task(T1, settle=True) is None
    assert W1 not in one.worlds and T1 not in one.tasks
    seed(two, worlds={W1: world()}, tasks={T1: task()})
    assert one.load_world(W1, settle=True) == world() and one.load_task(T1, settle=True) == task(), (
        "a miss is a 404 once, never remembered"
    )
    reads, real = [], pw1b_rig.backend.read
    pw1b_rig.backend.read = lambda *a: (reads.append(a), real(*a))[1]
    try:
        assert [
            one.load_world("w_x/../../o", settle=True),
            one.load_world(W1 + "/events", settle=True),
            one.load_task("t_../x", settle=True),
        ] == [None] * 3
    finally:
        del pw1b_rig.backend.read
    assert reads == []


def test_PROD_WIRE_1b_event_parts_join_the_queue_in_the_same_commit_and_drain_oldest_first(pw1b_rig) -> None:
    store, _ = pw1b_rig.process()
    seed(store, worlds={W1: world()})
    parts = [requested(1), part(2), part(3)]
    store.commit(worlds={W1: world(paused=True)}, parts={W1: parts[:2]})
    store.commit(parts={W1: parts[2:]})
    assert pw1b_rig.backend.queue(W1) == parts and store.pending_events[W1] == parts and not pw1b_rig.stream(W1)
    store.drain(W1)
    stream = pw1b_rig.stream(W1)
    assert ids(stream) == ids(parts) and [e["seq"] for e in stream] == [1, 2, 3] and store.events[W1] == stream
    assert pw1b_rig.backend.queue(W1) == [] and not store.pending_events.get(W1)


@pytest.mark.parametrize("after_commit", [False, True], ids=["writer refused", "writer ambiguous"])
def test_PROD_WIRE_1b_a_failed_drain_leaves_parts_queued_and_the_next_load_resends_by_id(
    pw1b_rig, after_commit
) -> None:
    store, writer = pw1b_rig.process()
    seed(store, worlds={W1: world()})
    parts = [requested(1), part(2), part(3)]
    store.commit(parts={W1: parts})
    with refused(503, "store_unavailable"):
        store.drain(W1, FlakyWriter(writer, 2, after_commit=after_commit))
    assert ids(pw1b_rig.backend.queue(W1)) == ids(parts)[1:], "the first part is out; the failed one and the rest wait"
    writer.reopen()  # the process exits cleanly: its lease is released
    cold, _ = pw1b_rig.process()
    cold.load_world(W1, settle=True)
    stream = pw1b_rig.stream(W1)
    assert ids(stream) == ids(parts) and [e["seq"] for e in stream] == [1, 2, 3], "every event once, none twice"
    assert pw1b_rig.backend.queue(W1) == [] and cold.events[W1] == stream and not cold.pending_events.get(W1)


def test_PROD_WIRE_1b_a_cold_store_equals_the_warm_one_after_lazy_loads(pw1b_rig) -> None:
    warm, writer = pw1b_rig.process()
    seed(
        warm, worlds={W1: world(), W2: world(layout=VILLAGE, prior_world_id=W1, paused=True)}, tasks={T1: task()},
        policies={P1: policy(P1)}, policy_worlds={P1: W1}, parts={W1: [requested(1), part(2)]},
    )  # fmt: skip
    warm.drain(W1)
    writer.reopen()
    cold, _ = pw1b_rig.process()
    assert not (cold.worlds or cold.tasks or cold.policies), "nothing is loaded at start"
    cold.load_world(W1, settle=True)
    cold.load_world(W2, settle=True)
    cold.load_task(T1, settle=True)
    cold.load_owner(OWNER, settle=True)

    def seen(s):
        return (s.worlds, s.tasks, s.policies, s.policy_worlds, {w: e for w, e in s.events.items() if e})

    assert seen(cold) == seen(warm) and not any(cold.pending_events.values())
    assert cold.worlds[W2].layout == VILLAGE and cold.worlds[W1].owner_channels == ("web", "email")
    assert cold.tasks[T1].gaps == warm.tasks[T1].gaps and cold.tasks[T1].questions == warm.tasks[T1].questions


def test_PROD_WIRE_1b_load_owner_counts_the_earlier_grants_after_a_restart(pw1b_rig) -> None:
    warm, writer = pw1b_rig.process()
    seed(
        warm, worlds={W1: world(), W2: world(), W3: world(owner=OTHER)},
        policies={P1: policy(P1), P3: policy(P3, owner=OTHER)}, policy_worlds={P1: W1, P3: W3},
        parts={W1: [granted(1, W1, 40)], W2: [granted(2, W2, 30)], W3: [granted(3, W3, 99)]},
    )  # fmt: skip
    for w in (W1, W2, W3):
        warm.drain(w)
    writer.reopen()
    cold, _ = pw1b_rig.process()
    cold.load_owner(OWNER, settle=True)

    def earlier(s):  # the approve route's own expression for FR-INT-08's daily limits
        owned = sorted(w for w, r in s.worlds.items() if r.owner == OWNER)
        return [e for w in owned for e in s.events.get(w, []) if e["type"] == "budget.granted"]

    assert [e["data"]["cap"] for e in earlier(cold)] == [40, 30] and earlier(cold) == earlier(warm)
    assert W3 not in cold.worlds and set(cold.policies) == {P1}, "only this owner's worlds and policies load"


@settings(max_examples=25, deadline=None)
@given(ops=st.lists(st.sampled_from(["ok", "refused", "ambiguous"]), min_size=1, max_size=8))
def test_PROD_WIRE_1b_property_no_record_without_its_events_and_no_event_twice(ops: list[str]) -> None:
    rig = make_rig("memory")
    store, writer = rig.process()
    seed(store, worlds={W1: world()})
    start, landed = rig.backend.read("worlds", W1)["rev"], []
    for n, op in enumerate(ops, 1):
        store.load_world(W1, settle=True)  # an evicted entry reloads, and a load resends what is still queued
        change = {"worlds": {W1: world(run_id=f"r_pw1b_{n}")}, "parts": {W1: [part(n)]}}
        if op == "ok":
            store.commit(**change)
        else:
            with commits_fail(rig.backend, applied=op == "ambiguous"), refused(503, "store_unavailable"):
                store.commit(**change)
        if op != "refused":
            landed.append(part(n)["id"])
    store.load_world(W1, settle=True)
    store.drain(W1)
    stream = rig.stream(W1)
    assert ids(stream) == landed and [e["seq"] for e in stream] == list(range(1, len(landed) + 1))
    assert rig.backend.read("worlds", W1)["rev"] == start + len(landed) and rig.backend.queue(W1) == []
    writer.reopen()
    cold, _ = rig.process()
    cold.load_world(W1, settle=True)
    assert cold.worlds[W1] == store.worlds[W1] and cold.events.get(W1, []) == store.events.get(W1, [])
