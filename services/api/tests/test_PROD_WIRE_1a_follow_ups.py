"""PROD-WIRE slice 1a follow-ups (security and code review): a refused event is a fixed 409, a part's trace is kept
only when the validator accepts it, `reopen()` never waits on a busy world, and a scheduled start refuses with a fixed
code."""

from __future__ import annotations

import logging
import threading
import time
from types import SimpleNamespace
from typing import Any

import pytest
from _fr_agt_14_lib import SchedApi, l3_budget_policy
from tilo_api import deps, world_writer
from tilo_harness.schedule import RunStart, StartSkipped, slot_key
from tilo_harness.store import MemoryStore

LEAK = "EV-12 w_leak_world r_leak_run 01JLEAKEVENTID0000000000"  # what a validator message looks like
OWNER, WORLD, OTHER = "u_pw1_owner", "w_pw1_a", "w_pw1_b"


class _Rejecting:
    def append(self, world_id: str, part: dict) -> dict:
        raise deps.EventRejected(LEAK)


def _swap(flow: Any) -> None:
    flow.app.dependency_overrides[deps.get_event_writer] = lambda: _Rejecting()


def _assert_fixed_409(response: Any, caplog: pytest.LogCaptureFixture) -> None:
    assert (response.status_code, response.json()) == (409, {"detail": "the event was refused"})
    assert "EV-12" not in response.text and "EV-12" not in caplog.text and "w_leak_world" not in caplog.text


def test_PROD_WIRE_1a_follow_up_intake_with_a_refusing_writer_is_a_fixed_409_and_stores_nothing(
    clear_flow: Any, caplog: pytest.LogCaptureFixture
) -> None:
    _swap(clear_flow)
    with caplog.at_level(logging.DEBUG):
        response = clear_flow.intake()
    _assert_fixed_409(response, caplog)
    assert clear_flow.store.worlds == {} and clear_flow.store.tasks == {}


def test_PROD_WIRE_1a_follow_up_approaches_with_a_refusing_writer_is_a_fixed_409(
    clear_flow: Any, caplog: pytest.LogCaptureFixture
) -> None:
    task_id = clear_flow.new_task()["task_id"]
    _swap(clear_flow)
    with caplog.at_level(logging.DEBUG):
        response = clear_flow.approaches(task_id)
    _assert_fixed_409(response, caplog)
    assert clear_flow.store.tasks[task_id].approaches is None


def test_PROD_WIRE_1a_follow_up_approve_with_a_refusing_writer_is_a_fixed_409_and_grants_nothing(
    clear_flow: Any, caplog: pytest.LogCaptureFixture
) -> None:
    task_id = clear_flow.task_with_approaches()["task_id"]
    _swap(clear_flow)
    with caplog.at_level(logging.DEBUG):
        response = clear_flow.approve(task_id, "quick", 50)
    _assert_fixed_409(response, caplog)
    assert not clear_flow.store.tasks[task_id].granted and not clear_flow.store.policies


def test_PROD_WIRE_1a_follow_up_a_scheduled_start_refused_by_the_writer_is_a_fixed_skip_and_leaves_no_world(
    clear_flow: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from _fr_agt_14_lib import MON_0330Z

    sched = SchedApi(clear_flow, monkeypatch)
    sched.clock.set(MON_0330Z)
    source = sched.approved_task()
    sched.store.policies["pol_auto_budget"] = l3_budget_policy()
    record = sched.insert(source, "sched_a")
    run = RunStart(
        idempotency_key=slot_key("sched_a", MON_0330Z), schedule_id="sched_a", owner_user_id=record.owner_user_id,
        title=record.title, approved_brief_ref=record.approved_brief_ref, prior_world_id=None,
        budget_cap=record.budget_cap, slot=MON_0330Z, skipped=0, cache_namespace="sched_a",
    )  # fmt: skip
    starter = sched.starter(seams=SimpleNamespace(writer=_Rejecting()))
    before = set(sched.store.worlds)
    with caplog.at_level(logging.DEBUG), pytest.raises(StartSkipped) as skipped:
        starter.start(run)
    assert skipped.value.code == "event_refused" and "EV-12" not in str(skipped.value) + caplog.text
    assert set(sched.store.worlds) == before


# --- the adapter ---------------------------------------------------------------------------------------------------


def _part(n: int, world: str = WORLD, **over: Any) -> dict[str, Any]:
    part = {
        "id": f"01JB5VQ0000000000000{n:06d}", "type": "agent.idle", "actor": "A_director", "target": "A_director",
        "level": None, "district": None, "item": None, "severity": "info", "credits": 0, "cause": None, "vis": "all",
        "authz": None, "summary": "The Director is waiting.", "data": {}, "world_id": world,
    }  # fmt: skip
    return part | over


def _rig(*worlds: str) -> tuple[Any, deps.Store, MemoryStore]:
    store = deps.Store(worlds={w: deps.WorldRecord(owner=OWNER, districts={}, run_id="r_pw1_1") for w in worlds})
    backend = MemoryStore()
    return world_writer.WorldWriterAdapter(store, backend), store, backend


def test_PROD_WIRE_1a_follow_up_a_part_with_a_trace_keeps_it_and_a_part_without_gets_null() -> None:
    adapter, _store, _backend = _rig(WORLD)
    trace = {
        "model_role": "director", "profile": "flash-38", "tokens_in": 120, "tokens_out": 30, "tool": None,
        "latency_ms": 250, "archive_ref": None,
    }  # fmt: skip
    assert adapter.append(WORLD, _part(1, trace=trace))["trace"] == trace
    assert adapter.append(WORLD, _part(2))["trace"] == dict.fromkeys(trace)


def test_PROD_WIRE_1a_follow_up_a_part_with_an_invalid_trace_is_refused_not_stored() -> None:
    adapter, store, _backend = _rig(WORLD)
    with pytest.raises(deps.EventRejected):
        adapter.append(WORLD, _part(1, trace={"model_role": "director", "unknown": 1}))
    assert store.events == {}


def test_PROD_WIRE_1a_follow_up_a_held_world_lock_blocks_neither_reopen_nor_an_append_on_another_world(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(world_writer, "_REOPEN_LOCK_WAIT_S", 0.05)
    adapter, _store, backend = _rig(WORLD, OTHER)
    adapter.append(WORLD, _part(1))
    adapter.append(OTHER, _part(2, OTHER))
    held, release = threading.Event(), threading.Event()

    def hold() -> None:
        with adapter._lock(WORLD):  # a thread in the middle of an append to world A
            held.set()
            release.wait(10)

    holder = threading.Thread(target=hold, daemon=True)
    holder.start()
    assert held.wait(5)
    try:
        started = time.monotonic()
        assert adapter.append(OTHER, _part(3, OTHER))["seq"] == 2  # world B is not blocked by A's lock
        adapter.reopen()  # skips A, closes B
        assert time.monotonic() - started < 2
        assert backend.read_head(deps.ORG_ID, OTHER)["lease"] is None
        assert backend.read_head(deps.ORG_ID, WORLD)["lease"] is not None, "A was skipped, not closed"
    finally:
        release.set()
        holder.join(5)
    adapter.reopen()
    assert backend.read_head(deps.ORG_ID, WORLD)["lease"] is None


def test_PROD_WIRE_1a_follow_up_the_world_record_is_read_inside_the_world_lock() -> None:
    adapter, store, _backend = _rig(WORLD)
    seen: list[bool] = []
    real = store.worlds

    class _Spy(dict):
        def get(self, key: str, default: Any = None) -> Any:
            seen.append(adapter._lock(WORLD)._is_owned())  # type: ignore[attr-defined]
            return real.get(key, default)

    store.worlds = _Spy(real)
    adapter.append(WORLD, _part(1))
    assert seen == [True]
