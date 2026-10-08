"""PROD-WIRE slice 1b, ADR-0026 decisions 3 and 4: the two orphan-event cases slice 1a left open resolve through the
durable queue's resend by id (`PROD_WIRE_1b`). Over memory by default, on the emulator under `-m emulator`.

- A retried scheduled start reuses the world id `w_s{digest}`: it never gets a second `world.requested`, whether the
  first attempt's send failed before or after the event committed, and whether the retry is the same process or a
  restart.
- `budget.granted` followed by a failed `policy.changed`: the grant, its policy events, the scenario's policies and
  the task commit in one transaction, so the stream never claims a policy that was never stored, and no grant is in
  the stream without the task being granted.
"""

from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest
from _clint1_lib import FLOW_USER
from _fr_agt_14_lib import CADENCE, MON_0330Z, SUNDAY, TITLE, l3_budget_policy
from _pw1b_lib import W1, FlakyWriter, commits_fail, seed, wire, world
from tilo_api import runs, schedules
from tilo_api.durable_store import DurableStore
from tilo_harness.schedule import Cadence, RunStart, Schedule, slot_key

OWNER = FLOW_USER
APPROACH = {"id": "quick", "credits": {"min": 1, "max": 2}}
BRIEF = {"title": "Weekly digest", "sources": [], "audience": None}


@pytest.fixture
def store(pw1b_rig) -> DurableStore:
    """Replaces conftest's plain `store` for the `flow` fixture, as the other slice 1b flow tests do."""
    return pw1b_rig.process()[0]


class _Schedules:
    def __init__(self, record: Schedule) -> None:
        self.record = record

    def get(self, schedule_id: str) -> Schedule | None:
        return self.record if schedule_id == self.record.schedule_id else None


def _starter(store: DurableStore, writer: object) -> schedules.ScheduleStarter:
    record = Schedule(
        schedule_id="sched_a", owner_user_id=OWNER, title=TITLE, cadence=Cadence(**CADENCE), approved_brief_ref=W1,
        budget_cap=60.0, enabled=True, next_due=MON_0330Z, brief=copy.deepcopy(BRIEF), approach=copy.deepcopy(APPROACH),
        created_at=SUNDAY,
    )  # fmt: skip
    return schedules.ScheduleStarter(
        store=store, schedules=_Schedules(record), seams=SimpleNamespace(writer=writer), clock=lambda: SUNDAY
    )  # type: ignore[arg-type]


RUN_START = RunStart(
    idempotency_key=slot_key("sched_a", MON_0330Z), schedule_id="sched_a", owner_user_id=OWNER, title=TITLE,
    approved_brief_ref=W1, prior_world_id=None, budget_cap=60.0, slot=MON_0330Z, skipped=0, cache_namespace="sched_a",
)  # fmt: skip


@pytest.mark.parametrize("restart", [False, True], ids=["same process", "after a restart"])
@pytest.mark.parametrize("after_commit", [False, True], ids=["send refused", "send ambiguous"])
def test_PROD_WIRE_1b_a_retried_scheduled_start_never_gets_a_second_world_requested(
    pw1b_rig, monkeypatch: pytest.MonkeyPatch, after_commit: bool, restart: bool
) -> None:
    monkeypatch.setattr(runs, "Run", lambda *a: SimpleNamespace(main=lambda: None))
    store, writer = pw1b_rig.process()
    seed(
        store, worlds={W1: world(owner=OWNER)}, policies={"pol_auto_budget": l3_budget_policy(OWNER)},
        policy_worlds={"pol_auto_budget": W1},
    )  # fmt: skip
    with pytest.raises(Exception, match="store_unavailable"):  # the world and both events commit; the send fails
        _starter(store, FlakyWriter(writer, 2, after_commit=after_commit)).start(RUN_START)
    (world_id,) = [w for w in store.worlds if w != W1]
    assert len(pw1b_rig.stream(world_id)) == (2 if after_commit else 1), "the first event went out, the second maybe"
    assert len(pw1b_rig.backend.queue(world_id)) == 1, "what was not confirmed waits in the durable queue"
    if restart:
        writer.reopen()
        store, writer = pw1b_rig.process()
    assert _starter(store, writer).start(RUN_START) == world_id, "the retry reuses w_s{digest}"
    types = [e["type"] for e in pw1b_rig.stream(world_id)]
    assert types.count("world.requested") == 1 and types.count("budget.granted") == 1
    assert [e["seq"] for e in pw1b_rig.stream(world_id)] == [1, 2] and pw1b_rig.backend.queue(world_id) == []


def _approved_up_to_approaches(flow, store: DurableStore) -> str:
    wire(flow.app, store)
    body = flow.client.post("/intake", data={"text": "Compare competitor pricing.", "scenario": "SC-01"}).json()
    skipped = [{"field": q["field"], "answer": None} for q in body["questions"]]
    assert flow.answers(body["task_id"], skipped).status_code == 200
    assert flow.approaches(body["task_id"]).status_code == 200
    return body["task_id"]


def _claims_only_stored_policies(pw1b_rig, store: DurableStore, world_id: str) -> None:
    for event in pw1b_rig.stream(world_id):
        if event["type"] == "policy.changed" and event["data"]["change"] == "created":
            assert pw1b_rig.backend.read("policies", event["data"]["policy_id"]) is not None, (
                "the stream claims a policy that was never stored"
            )


def test_PROD_WIRE_1b_a_failed_commit_at_approve_leaves_no_grant_in_the_stream(flow, store, pw1b_rig) -> None:
    task_id = _approved_up_to_approaches(flow, store)
    world_id = store.tasks[task_id].world_id
    before = [e["type"] for e in pw1b_rig.stream(world_id)]
    with commits_fail(pw1b_rig.backend):
        refused = flow.approve(task_id, "quick", 50)
    assert (refused.status_code, refused.json()) == (503, {"detail": "store_unavailable"})
    assert [e["type"] for e in pw1b_rig.stream(world_id)] == before and "budget.granted" not in before
    assert not pw1b_rig.backend.read("tasks", task_id)["granted"] and not store.policies
    assert flow.approve(task_id, "quick", 50).status_code == 200, "the retry builds the grant once"
    types = [e["type"] for e in pw1b_rig.stream(world_id)]
    assert types.count("budget.granted") == 1
    _claims_only_stored_policies(pw1b_rig, store, world_id)


@pytest.mark.parametrize("after_commit", [False, True], ids=["send refused", "send ambiguous"])
def test_PROD_WIRE_1b_budget_granted_then_a_failed_policy_changed_never_claims_an_unstored_policy(
    flow, store, pw1b_rig, after_commit: bool
) -> None:
    task_id = _approved_up_to_approaches(flow, store)
    world_id, writer = store.tasks[task_id].world_id, store.writer
    wire(flow.app, store, FlakyWriter(writer, 2, after_commit=after_commit))  # budget.granted goes out, then it fails
    refused = flow.approve(task_id, "quick", 50)
    assert (refused.status_code, refused.json()) == (503, {"detail": "store_unavailable"})
    stored = pw1b_rig.backend.read("tasks", task_id)
    assert stored["granted"] and pw1b_rig.backend.read("policies", next(iter(store.policies)))["world_id"] == world_id
    _claims_only_stored_policies(pw1b_rig, store, world_id)
    assert [e["type"] for e in pw1b_rig.stream(world_id)].count("budget.granted") == 1
    writer.reopen()
    cold, _ = pw1b_rig.process()
    cold.load_world(world_id, settle=True)  # the restart resends what is queued, by id
    types = [e["type"] for e in pw1b_rig.stream(world_id)]
    assert types.count("budget.granted") == 1 and types.count("policy.changed") == len(store.policies)
    assert pw1b_rig.backend.queue(world_id) == []
    _claims_only_stored_policies(pw1b_rig, cold, world_id)
