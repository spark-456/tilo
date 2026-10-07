"""PROD-WIRE slice 1b, the review round (ADR-0026 decisions 3, 4 and 5): a kill switch's unsaved change is kept until a
commit lands and never waits on a read or on the store's lock; the door refuses any emulator host on Cloud Run; a run
and a scheduled start load the owner's records; a stranger's request writes nothing; the restart's `world.failed` has
one id; ids are matched whole; decoding failures are 503; an eviction reloads the queue; a tick opens nothing before
its token; free-form fields survive Firestore's no-nested-arrays rule. Over memory by default, on the emulator under
`-m emulator`.
"""

from __future__ import annotations

import copy
import threading
import time
from types import SimpleNamespace

import pytest
from _api_lib import as_principal, make_principal
from _clint1_lib import FLOW_USER
from _fr_agt_14_lib import l3_budget_policy
from _pw1b_lib import (
    OWNER,
    P1,
    P2,
    RUN,
    T1,
    W1,
    W2,
    commits_fail,
    part,
    policy,
    requested,
    seed,
    started,
    task,
    wire,
    world,
)
from fastapi import HTTPException
from fastapi.testclient import TestClient
from test_PROD_WIRE_1b_orphan_events import RUN_START, _starter
from tilo_api import app, deps, durable_store, runs, store_door
from tilo_api.runs import Run
from tilo_api.schedules import ENV_AUDIENCE, ENV_CALLER

BUDGET_S = 4.5  # FR-HIL-07's call budget (dispatch._CALL_BUDGET_S)
PAUSE, STOP, REVOKE = f"/worlds/{W1}/pause", f"/worlds/{W1}/autopilot/stop", f"/policies/{P1}/revoke"


def _rig(rig):
    store, writer = rig.process()
    seed(
        store, worlds={W1: world(), W2: world()}, policies={P1: policy(P1, level="L2"), P2: policy(P2, level="L3")},
        policy_worlds={P1: W1, P2: W2},
    )  # fmt: skip
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=W1))
    wire(app, store)
    return store, writer


def _cold_levels(rig) -> tuple[list[str], bool]:
    cold, _ = rig.process()
    cold.load_owner(OWNER)
    return [cold.policies[p]["level"] for p in (P1, P2)], cold.worlds[W1].paused


@pytest.mark.parametrize("first", [PAUSE, STOP, REVOKE])
def test_PROD_WIRE_1b_a_kill_switch_retry_saves_what_the_failed_one_left_unsaved(client, pw1b_rig, first: str) -> None:
    store, _ = _rig(pw1b_rig)
    with commits_fail(pw1b_rig.backend):
        assert client.post(first).status_code == 503
        again = client.post(first)  # nothing new to lower now, yet it is still not saved: never 200 or 202
        assert again.status_code == 503 and "not saved" in again.text
    assert store.policies[P1]["level"] == "L1", "applied here all along, so a run still stops"
    assert pw1b_rig.backend.read("policies", P1)["record"]["level"] == "L2"
    for path in (PAUSE, STOP):  # the next switches, whichever they are, save every change still pending
        assert client.post(path).status_code in (200, 202)
    levels = [pw1b_rig.backend.read("policies", p)["record"]["level"] for p in (P1, P2)]
    assert levels[0] == "L1" and (first == REVOKE or levels == ["L1", "L1"])
    assert pw1b_rig.backend.read("worlds", W1)["paused"] is True
    cold_levels, cold_paused = _cold_levels(pw1b_rig)
    assert cold_levels[0] == "L1" and cold_paused is True
    assert not store.unsaved["policies"] and not store.unsaved["worlds"]


def test_PROD_WIRE_1b_a_retried_pause_sends_each_event_once(client, pw1b_rig) -> None:
    store, writer = _rig(pw1b_rig)
    with commits_fail(pw1b_rig.backend):
        assert client.post(PAUSE).status_code == 503
    assert client.post(PAUSE).status_code in (200, 202)
    writer.reopen()
    cold, _ = pw1b_rig.process()
    cold.load_world(W1)
    types = [e["type"] for e in pw1b_rig.stream(W1)]
    assert types.count("world.paused") == 1 and pw1b_rig.backend.queue(W1) == []


def test_PROD_WIRE_1b_pause_all_applies_the_cached_change_when_the_owner_cannot_be_read(
    client, pw1b_rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, _ = _rig(pw1b_rig)

    def refuse(*_a: object) -> list:
        raise TimeoutError("the query did not answer")

    monkeypatch.setattr(pw1b_rig.backend, "find", refuse)
    with commits_fail(pw1b_rig.backend):  # the read fails and so does the save: the change is kept and marked
        started_at = time.monotonic()
        response = client.post(PAUSE)
        assert time.monotonic() - started_at < BUDGET_S
    assert response.status_code == 503 and "not saved" in response.text
    assert store.worlds[W1].paused is True and [store.policies[p]["level"] for p in (P1, P2)] == ["L1", "L1"]
    assert store.unsaved["worlds"] == {W1} and store.unsaved["policies"] == {P1, P2}
    again = client.post(PAUSE)  # the read still fails; the save works: the cached change lands, and it is still 503
    assert again.status_code == 503 and "not saved" in again.text
    assert pw1b_rig.backend.read("worlds", W1)["paused"] is True and not store.unsaved["policies"]
    assert [pw1b_rig.backend.read("policies", p)["record"]["level"] for p in (P1, P2)] == ["L1", "L1"]


def test_PROD_WIRE_1b_a_kill_switch_never_waits_on_the_store_lock_past_its_budget(client, pw1b_rig) -> None:
    store, _ = _rig(pw1b_rig)
    held, release = threading.Event(), threading.Event()

    def hold() -> None:  # another request's commit, stuck in Firestore with the process-wide lock
        with store._lock:
            held.set()
            release.wait(15)

    holder = threading.Thread(target=hold, daemon=True)
    holder.start()
    assert held.wait(5)
    try:
        for path in (PAUSE, STOP):
            started_at = time.monotonic()
            response = client.post(path)
            assert time.monotonic() - started_at < BUDGET_S, path
            assert response.status_code == 503 and "not saved" in response.text
        assert store.worlds[W1].paused is True and [store.policies[p]["level"] for p in (P1, P2)] == ["L1", "L1"]
    finally:
        release.set()
        holder.join(5)
    assert client.post(STOP).status_code in (200, 202), "the lock is free: the pending changes save"
    assert [pw1b_rig.backend.read("policies", p)["record"]["level"] for p in (P1, P2)] == ["L1", "L1"]


def test_PROD_WIRE_1b_the_door_refuses_any_emulator_host_on_cloud_run_whatever_the_project() -> None:
    env = {"K_SERVICE": "tilo-api", "TILO_API_STORE": "firestore", "TILO_FIRESTORE_PROJECT": "demo-pw1b"}
    built: list[str] = []

    def factory(project: str) -> object:
        built.append(project)
        return object()

    with pytest.raises(store_door.ApiStoreNotConfigured):
        store_door.open_api_store(
            {**env, "FIRESTORE_EMULATOR_HOST": "127.0.0.1:8199"}, firestore_client_factory=factory
        )
    assert built == []


def test_PROD_WIRE_1b_the_door_refuses_an_emulator_host_in_os_environ_for_a_demo_project_on_cloud_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", "127.0.0.1:8199")
    env = {"K_SERVICE": "tilo-api", "TILO_API_STORE": "firestore", "TILO_FIRESTORE_PROJECT": "demo-pw1b"}
    with pytest.raises(store_door.ApiStoreNotConfigured):
        store_door.open_api_store(env, firestore_client_factory=lambda project: object())


def _plant(rig, world_id: str, event: dict) -> None:
    """An event straight into the events store (the harness validator is not under test here)."""
    head = {"last_seq": event["seq"], "lease": None, "view_seq": {}}
    rig.events.transact(rig.org, world_id, lambda _h: (head, event, []))


def test_PROD_WIRE_1b_a_run_loads_the_owners_records_and_counts_the_daily_cap_from_stored_history(pw1b_rig) -> None:
    warm, writer = pw1b_rig.process()
    seed(
        warm, worlds={W1: world(), W2: world()}, tasks={T1: task(granted=True)}, policies={P1: policy(P1)},
        policy_worlds={P1: W2},
    )  # fmt: skip
    applied = {
        "v": "1.0", "id": "01JB5VQ0000000000000000133", "seq": 1, "ts": "2026-09-29T09:42:13.000Z", "world_id": W2,
        "run_id": RUN, "type": "policy.applied", "actor": P1, "target": "G1", "level": "L1", "district": "D1",
        "item": None, "severity": "info", "credits": 0, "summary": "A policy opened the gate.", "cause": None,
        "vis": "all", "authz": {"by": "policy", "ref": P1, "at": "2026-09-29T09:42:16.000Z"}, "data": {},
        "trace": dict.fromkeys(
            ("model_role", "profile", "tokens_in", "tokens_out", "tool", "latency_ms", "archive_ref")
        ),
    }  # fmt: skip
    _plant(pw1b_rig, W2, applied)
    writer.reopen()
    cold, cold_writer = pw1b_rig.process()
    assert cold.load_task(T1) is not None and W2 not in cold.worlds and P1 not in cold.policies

    def no_plan(**_kw: object) -> dict:
        raise RuntimeError("the test stops the run after it has loaded the owner")

    seams = SimpleNamespace(
        connectors=SimpleNamespace(ids=lambda: []), skills=SimpleNamespace(catalog=lambda: {}), compiler=no_plan,
        writer=cold_writer,
    )  # fmt: skip
    run = Run(cold, cold.tasks[T1], {}, 40.0, seams)  # type: ignore[arg-type]
    assert run._prepare() is None
    assert W2 in cold.worlds and P1 in cold.policies, "the owner's other worlds and policies were loaded"
    assert [e["id"] for e in run._applied()] == [applied["id"]], "the daily cap counts the stored history"


def test_PROD_WIRE_1b_a_scheduled_start_loads_the_owner_before_it_looks_for_the_world(
    pw1b_rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runs, "Run", lambda *a: SimpleNamespace(main=lambda: None))
    warm, writer = pw1b_rig.process()
    seed(
        warm, worlds={W1: world(owner=FLOW_USER)}, policies={"pol_auto_budget": l3_budget_policy(FLOW_USER)},
        policy_worlds={"pol_auto_budget": W1},
    )  # fmt: skip
    _starter(warm, writer).start(RUN_START)
    writer.reopen()
    cold, cold_writer = pw1b_rig.process()
    assert cold.worlds == {} and cold.policies == {}
    assert _starter(cold, cold_writer).start(RUN_START)  # the world exists, only in the backend
    assert W1 in cold.worlds and "pol_auto_budget" in cold.policies, "the retry path loaded the owner first"
    types = [e["type"] for e in pw1b_rig.stream(next(w for w in cold.worlds if w != W1))]
    assert types.count("world.requested") == 1


def _stopped_world(rig) -> None:
    warm, writer = rig.process()
    seed(warm, worlds={W1: world()}, parts={W1: [requested(1), started(2)]})
    warm.drain(W1)
    writer.reopen()


def test_PROD_WIRE_1b_a_strangers_request_writes_nothing_and_the_owners_gets_the_restarts_world_failed(
    client, pw1b_rig
) -> None:
    _stopped_world(pw1b_rig)
    cold, _ = pw1b_rig.process()
    wire(app, cold)
    before = pw1b_rig.stream(W1)
    for who in (make_principal(user_id="u_pw1b_other", role="owner", world_id=None),
                make_principal(user_id="u_pw1b_other", role="owner", world_id="w_pw1b_elsewhere")):  # fmt: skip
        as_principal(who)
        assert client.get(f"/worlds/{W1}/events").status_code == 404
        assert client.post(PAUSE).status_code == 404
        assert client.post(STOP).status_code == 404
    assert pw1b_rig.stream(W1) == before, "no `world.failed`, no drained part: a stranger changed nothing"
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=W1))
    response = client.get(f"/worlds/{W1}/events")
    assert response.status_code == 200 and response.json()["events"][-1]["type"] == "world.failed"
    assert [e["type"] for e in pw1b_rig.stream(W1)].count("world.failed") == 1


def test_PROD_WIRE_1b_two_loaders_of_one_started_world_write_one_world_failed(pw1b_rig) -> None:
    _stopped_world(pw1b_rig)
    one, _ = pw1b_rig.process()
    two, _ = pw1b_rig.process()
    one.load_world(W1, settle=False)  # both have read the stream before either writes: a rollover
    two.load_world(W1, settle=False)
    one.settle(W1)
    two.settle(W1)
    ((first,),) = [[e for e in pw1b_rig.stream(W1) if e["type"] == "world.failed"]]
    assert first["id"] == durable_store.events.world_failed_part(W1, durable_store.RESTARTED, RUN)["id"]
    assert len([e for e in pw1b_rig.stream(W1) if e["type"] == "world.failed"]) == 1


def test_PROD_WIRE_1b_an_id_is_matched_whole_and_checked_at_every_backend_call(pw1b_rig) -> None:
    store, _ = pw1b_rig.process()
    seed(store, worlds={W1: world()})
    reads: list[tuple] = []
    real = pw1b_rig.backend.read
    pw1b_rig.backend.read = lambda *a: (reads.append(a), real(*a))[1]
    try:
        assert store.load_world(W1 + "\n") is None and store.load_task("t_" + "0" * 25 + "1\n") is None
    finally:
        del pw1b_rig.backend.read
    assert reads == []
    for call in (
        lambda: pw1b_rig.backend.read("worlds", W1 + "\n"),
        lambda: pw1b_rig.backend.queue(W1 + "\n"),
        lambda: pw1b_rig.backend.ack(W1 + "\n", "x"),
        lambda: pw1b_rig.backend.commit([("worlds", W1 + "\n", {}, None)], {}),
        lambda: pw1b_rig.backend.commit([], {W1 + "/x": [part(1)]}),
    ):
        with pytest.raises(ValueError):
            call()
    with pytest.raises(HTTPException) as refused:
        store.commit(worlds={"w_ok\n": world()}, create=[("worlds", "w_ok\n")])
    assert (refused.value.status_code, refused.value.detail) == (503, "store_unavailable")


def test_PROD_WIRE_1b_a_world_that_stays_cached_gets_its_durable_queue_back_after_a_failed_commit(pw1b_rig) -> None:
    store, _ = pw1b_rig.process()
    seed(store, worlds={W1: world()}, parts={W1: [requested(1)]})  # queued, not yet sent
    with commits_fail(pw1b_rig.backend), pytest.raises(HTTPException):
        store.commit(parts={W1: [part(2)]})
    assert W1 in store.worlds, "the world record was not touched"
    assert [p["id"] for p in store.pending_events[W1]] == [requested(1)["id"]], "its stored queue, read again"


def test_PROD_WIRE_1b_a_malformed_stored_record_is_503_store_unavailable_never_a_traceback(pw1b_rig) -> None:
    warm, _ = pw1b_rig.process()
    seed(warm, worlds={W1: world()}, tasks={T1: task()}, policies={P1: policy(P1)}, policy_worlds={P1: W1})
    if not hasattr(pw1b_rig.backend, "docs"):
        pytest.skip("the documents are damaged in the memory backend; the decoding is the same code")
    for key, field in ((("tasks", T1), "gaps"), (("worlds", W1), "owner"), (("policies", P1), "rev")):
        del pw1b_rig.backend.docs[key][field]
    for load in (
        lambda s: s.load_task(T1), lambda s: s.load_world(W1), lambda s: s.load_owner(OWNER),
        lambda s: s.load_path({"policy_id": P1}),
    ):  # fmt: skip
        cold, _ = pw1b_rig.process()
        with pytest.raises(HTTPException) as refused:
            load(cold)
        assert (refused.value.status_code, refused.value.detail) == (503, "store_unavailable")


def test_PROD_WIRE_1b_free_form_fields_with_nested_arrays_store_and_reload(pw1b_rig) -> None:
    grid = {"matrix": [[1, 2], [3]], "rows": [{"cells": [[0.5], [1.5, 2.5]]}]}
    brief = {"title": "Compare prices", "sources": [], "audience": None, **grid}
    approaches = [{"id": "quick", "credits": {"min": 1, "max": 2}, "steps": [[1, 2], [3]]}]
    warm, writer = pw1b_rig.process()
    nested = task(
        draft=copy.deepcopy(brief), brief=copy.deepcopy(brief), edits={"grid": [[1], [2, 3]]}, approaches=approaches
    )
    seed(
        warm, worlds={W1: world(layout={"semantic": {"points": [[0, 0], [1, 1]]}})}, tasks={T1: nested},
        policies={P1: policy(P1)}, policy_worlds={P1: W1},
    )  # fmt: skip
    writer.reopen()
    cold, _ = pw1b_rig.process()
    cold.load_task(T1)
    cold.load_owner(OWNER)
    assert cold.tasks[T1] == nested and cold.worlds[W1] == warm.worlds[W1] and cold.policies[P1] == policy(P1)


def test_PROD_WIRE_1b_close_deployed_is_bounded_and_reads_the_table_under_its_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    budgets: list[float] = []
    monkeypatch.setattr(durable_store, "_opened", {("a",): (None, SimpleNamespace(reopen=budgets.append))})
    held, release = threading.Event(), threading.Event()

    def hold() -> None:  # a client being built holds the table's lock
        with durable_store._opening:
            held.set()
            release.wait(10)

    holder = threading.Thread(target=hold, daemon=True)
    holder.start()
    assert held.wait(5)
    started_at = time.monotonic()
    try:
        durable_store.close_deployed()
    finally:
        release.set()
        holder.join(5)
    assert time.monotonic() - started_at < 3, "a busy table does not hold the shutdown up"
    assert len(budgets) == 1 and 0 < budgets[0] <= 5.0, "the whole shutdown is bounded, under Cloud Run's 10 s"


def test_PROD_WIRE_1b_the_adapter_reopen_stops_waiting_when_its_budget_is_spent() -> None:
    from tilo_api.world_writer import WorldWriterAdapter
    from tilo_harness.store import MemoryStore

    store = deps.Store(worlds={f"w_pw1b_{n}": deps.WorldRecord(owner=OWNER, districts={}) for n in range(6)})
    adapter = WorldWriterAdapter(store, MemoryStore())
    for world_id in store.worlds:
        adapter.append(world_id, part(1))
    gates = []
    for world_id in store.worlds:  # every world mid-append: all six stripes are held
        gate = threading.Event()
        gates.append(gate)
        locked = threading.Event()

        def hold(w: str = world_id, g: threading.Event = gate, l: threading.Event = locked) -> None:  # noqa: E741
            with adapter._lock(w):
                l.set()
                g.wait(10)

        threading.Thread(target=hold, daemon=True).start()
        assert locked.wait(5)
    started_at = time.monotonic()
    adapter.reopen(0.3)
    elapsed = time.monotonic() - started_at
    for gate in gates:
        gate.set()
    assert elapsed < 1.5, "six busy worlds cost the budget once, not a second each"


@pytest.fixture
def _tick_deployed(monkeypatch: pytest.MonkeyPatch):
    for name in ("TILO_API_DEV", "LIVE", "FIRESTORE_EMULATOR_HOST"):
        monkeypatch.delenv(name, raising=False)
    for name, value in {
        "K_SERVICE": "tilo-api", "TILO_API_STORE": "firestore", "TILO_FIRESTORE_PROJECT": "tilo-dev",
        ENV_AUDIENCE: "https://tilo-api.example/tick", ENV_CALLER: "scheduler@tilo-dev.example",
    }.items():  # fmt: skip
        monkeypatch.setenv(name, value)
    asked: list[str] = []
    monkeypatch.setattr(store_door, "client_factory", lambda project: asked.append(project) or object())
    monkeypatch.setattr(durable_store, "_opened", {})
    saved = dict(app.dependency_overrides)
    app.dependency_overrides.clear()
    yield asked
    app.dependency_overrides.clear()
    app.dependency_overrides.update(saved)


def test_PROD_WIRE_1b_an_anonymous_tick_opens_no_client_and_is_401_before_any_503(_tick_deployed) -> None:
    response = TestClient(app).post("/internal/schedules/tick")
    assert response.status_code == 401
    bad = TestClient(app).post("/internal/schedules/tick", headers={"Authorization": "Bearer not-a-token"})
    assert bad.status_code == 401
    assert _tick_deployed == [], "no Firestore client was built for a caller with no valid token"
