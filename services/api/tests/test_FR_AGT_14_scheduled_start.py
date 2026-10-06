"""FR-AGT-14b (design decisions 3, 4 and 6; PRD 8.6, 10.1, 10.4, 9.4): a due schedule starts a run in tilo-api.

What the tick route's starter (`tilo_api.schedules.ScheduleStarter`) must do, driven through the real route, the real
in-memory schedule store on a fake clock, and the CL-INT-2 run seams (scripted unit runner, mock connector):

- the fire creates a world owned by the schedule's owner whose first event is `world.requested` on channel `schedule`,
  then a `budget.granted` and the run; the world and run ids are a function of the slot (the idempotency key) alone, so
  two starts of one slot meet ONE world and ONE run, even from many threads, and even after a start that raised;
- the budget comes only from the owner's own L3 `grant_budget` policy through the deterministic policy engine. No
  covering policy: the firing is skipped, nothing is created, the failure is recorded under a fixed code and the
  schedule retries next week, not every minute. A person's earlier approval is never reused: a fired run's send still
  waits at its gate for a person;
- a start that raises, or runs with unwired seams, backs off and is retried for the same slot; 20 failing schedules do
  not starve a healthy 21st.

API_FR_AGT_14b.md pins every name used here. No model call, no network, no sleep beyond the scripted runner's polling.
"""

from __future__ import annotations

import re
import threading
from datetime import timedelta
from typing import Any

import pytest
from _api_contracts_lib import assert_valid_event
from _clint1_lib import registered_event_types
from _clint2_lib import REPO_ROOT, build_run_flow, settle, wait_for
from _fr_agt_14_lib import (
    CAP,
    FLOW_USER,
    MON_0330Z,
    TITLE,
    WEEK,
    SchedApi,
    l3_budget_policy,
)
from tilo_harness.schedule import RunStart, slot_key, world_requested_kwargs

WORLD_ID = re.compile(r"^w_[0-9A-Za-z_]{1,48}$")
RUN_ID = re.compile(r"^r_[0-9A-Za-z_]{1,48}$")
CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
POLICY_ID = "pol_auto_budget"


@pytest.fixture
def rig(run_flow, monkeypatch) -> SchedApi:
    return SchedApi(run_flow.flow, monkeypatch, rf=run_flow)


def armed(rig: SchedApi, **policy: Any) -> Any:
    """The source task approved by the owner (a person's grant), its run quiet at the gate, and the owner's standing L3
    budget policy installed for what fires later."""
    source = rig.source_run_task()
    rig.store.policies[POLICY_ID] = l3_budget_policy(**policy)
    return source


def fire(rig: SchedApi, at: Any = MON_0330Z) -> int:
    rig.clock.set(at)
    response = rig.tick()
    assert response.status_code == 200, response.text
    return response.json()["fired"]


def world_of(rig: SchedApi, schedule_id: str) -> str:
    world_id = rig.schedules.get(schedule_id).last_world_id
    assert world_id, f"{schedule_id} has not fired"
    return world_id


def types(rig: SchedApi, world_id: str) -> list[str]:
    return [e["type"] for e in rig.events(world_id)]


def settled(rig: SchedApi, world_id: str) -> list[dict[str, Any]]:
    settle(lambda: len(rig.events(world_id)), quiet_s=0.5)
    return rig.events(world_id)


def run_start(rig: SchedApi, schedule_id: str, **over: Any) -> RunStart:
    record = rig.schedules.get(schedule_id)
    slot = over.pop("slot", MON_0330Z)
    fields: dict[str, Any] = {
        "idempotency_key": slot_key(schedule_id, slot), "schedule_id": schedule_id,
        "owner_user_id": record.owner_user_id, "title": record.title, "approved_brief_ref": record.approved_brief_ref,
        "prior_world_id": None, "budget_cap": record.budget_cap, "slot": slot, "skipped": 0,
        "cache_namespace": schedule_id,
    }  # fmt: skip
    return RunStart(**{**fields, **over})


# --- the fire --------------------------------------------------------------------------------------------------------


def test_FR_AGT_14_a_due_schedule_creates_the_owners_world_and_starts_its_run(rig: SchedApi, registry) -> None:
    source = armed(rig)
    view = rig.created(source)
    sid = view["schedule_id"]
    snapshot = rig.schedules.get(sid)
    assert fire(rig) == 1

    record = rig.schedules.get(sid)
    world_id = world_of(rig, sid)
    assert WORLD_ID.match(world_id) and world_id != source.world_id
    assert rig.store.worlds[world_id].owner == FLOW_USER and RUN_ID.match(rig.store.worlds[world_id].run_id)
    assert (record.last_slot, record.next_due) == (slot_key(sid, MON_0330Z), MON_0330Z + WEEK)
    assert (record.failures, record.last_error, record.backoff_until) == (0, None, None)

    wait_for(lambda: rig.events(world_id, "world.started"), what="the scheduled run to start")
    stream = settled(rig, world_id)
    first = stream[0]
    assert (first["type"], first["seq"], first["actor"], first["target"]) == ("world.requested", 1, FLOW_USER, world_id)
    expected = world_requested_kwargs(run_start(rig, sid), world_id)
    assert first["data"] == expected["data"] == {"title": TITLE, "channel": "schedule", "destination": None}

    kinds = [e["type"] for e in stream]
    assert kinds.index("world.requested") < kinds.index("budget.granted") < kinds.index("world.started")
    (grant,) = [e for e in stream if e["type"] == "budget.granted"]
    assert grant["data"] == {"granted": CAP, "cap": CAP}
    assert grant["authz"]["by"] == "policy" and grant["authz"]["ref"] == POLICY_ID  # the owner's rule, not a person
    (started,) = [e for e in stream if e["type"] == "world.started"]
    assert started["data"]["budget_cap"] == CAP

    call = rig.rf.compile_calls[-1]  # the plan is compiled from what the owner approved, not from anything new
    assert call["cap"] == CAP and call["approach"] == snapshot.approach and call["brief"] == snapshot.brief

    assert [e["seq"] for e in stream] == list(range(1, len(stream) + 1))
    assert len({e["id"] for e in stream}) == len(stream)
    assert {e["type"] for e in stream} <= registered_event_types(REPO_ROOT)
    for event in stream:
        assert_valid_event(REPO_ROOT, registry, event)


def test_FR_AGT_14_the_fired_run_does_not_touch_the_source_world(rig: SchedApi) -> None:
    source = armed(rig)
    rig.created(source)
    before = [e["id"] for e in rig.events(source.world_id)]
    assert fire(rig) == 1
    settled(rig, world_of(rig, rig.listing().json()["schedules"][0]["schedule_id"]))
    assert [e["id"] for e in rig.events(source.world_id)] == before
    assert len(rig.worlds_besides(source.world_id)) == 1


def test_FR_AGT_14_the_world_and_run_ids_depend_only_on_the_slot(
    rig: SchedApi, run_flow, monkeypatch, repo_root
) -> None:
    source = armed(rig)
    rig.insert(source, "sched_fixed_1")
    fire(rig)
    first_world = world_of(rig, "sched_fixed_1")
    first_run = rig.store.worlds[first_world].run_id
    settled(rig, first_world)
    run_flow.close()

    second_flow = build_run_flow(repo_root, covered=True)  # a fresh process in effect: new store, new schedule store
    try:
        again = SchedApi(second_flow.flow, monkeypatch, rf=second_flow)
        source_2 = again.source_run_task()
        again.store.policies[POLICY_ID] = l3_budget_policy()
        again.insert(source_2, "sched_fixed_1")
        fire(again)
        second_world = world_of(again, "sched_fixed_1")
        assert second_world == first_world
        assert again.store.worlds[second_world].run_id == first_run
        again.insert(source_2, "sched_fixed_2")
        fire(again)
        assert world_of(again, "sched_fixed_2") != first_world  # another schedule, another slot key: another world
        settled(again, second_world)
    finally:
        second_flow.close()


def test_FR_AGT_14_two_starts_of_one_slot_meet_one_world_and_one_run(rig: SchedApi) -> None:
    source = armed(rig)
    rig.insert(source, "sched_a")
    ran_before = list(rig.rf.runner.ran)
    run = run_start(rig, "sched_a")
    starter = rig.starter()

    first = starter.start(run)
    second = starter.start(run)  # the Ticker's claim lost or a Cloud Tasks style retry: same key

    assert first == second
    stream = settled(rig, first)
    assert types(rig, first).count("world.requested") == 1
    assert types(rig, first).count("budget.granted") == 1
    assert types(rig, first).count("world.started") == 1
    assert rig.worlds_besides(source.world_id) == [first]
    assert rig.rf.runner.ran[len(ran_before) :] == ["U1", "U2", "U3", "U4"]  # the run executed once
    assert [e["seq"] for e in stream] == list(range(1, len(stream) + 1))


def test_FR_AGT_14_many_threads_starting_one_slot_at_once_still_meet_one_world_and_one_run(rig: SchedApi) -> None:
    source = armed(rig)
    rig.insert(source, "sched_a")
    ran_before = list(rig.rf.runner.ran)
    run, starter = run_start(rig, "sched_a"), rig.starter()
    results: list[str] = []
    errors: list[BaseException] = []
    barrier, lock = threading.Barrier(8), threading.Lock()

    def worker() -> None:
        barrier.wait(timeout=10)
        try:
            world_id = starter.start(run)
        except BaseException as exc:  # noqa: BLE001 - reported by the assertion below
            with lock:
                errors.append(exc)
            return
        with lock:
            results.append(world_id)

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, errors
    assert len(set(results)) == 1 and len(results) == 8
    world_id = results[0]
    settled(rig, world_id)
    assert rig.worlds_besides(source.world_id) == [world_id]
    for once in ("world.requested", "budget.granted", "world.started"):
        assert types(rig, world_id).count(once) == 1, once
    assert rig.rf.runner.ran[len(ran_before) :] == ["U1", "U2", "U3", "U4"]


def test_FR_AGT_14_a_start_is_taken_from_the_stored_snapshot_never_from_what_it_is_handed(rig: SchedApi) -> None:
    """RunStart is built from the record by the Ticker, but the starter is the last line: a wrong owner or a bigger cap
    in the RunStart must neither start the run for someone else nor grant more than the owner approved."""
    source = armed(rig)
    rig.store.policies["pol_other"] = l3_budget_policy("u_other", id_="pol_other", credits=10_000.0)
    rig.insert(source, "sched_a")
    for over in ({"owner_user_id": "u_other"}, {"budget_cap": 9999.0}):
        try:
            rig.starter().start(run_start(rig, "sched_a", **over))
        except Exception:  # refusing is allowed
            continue
    assert not [w for w in rig.store.worlds.values() if w.owner == "u_other"]
    for world_id in rig.worlds_besides(source.world_id):
        settled(rig, world_id)
        for event in rig.events(world_id):
            assert event["actor"] != "u_other"
        grants = rig.events(world_id, "budget.granted")
        assert all(g["data"]["cap"] == CAP and g["data"]["granted"] == CAP for g in grants), grants


# --- the budget comes from the owner's policy only --------------------------------------------------------------------

NOT_COVERED = {
    "no policy at all": None,
    "an L3 policy of another owner": l3_budget_policy("u_other", id_="pol_theirs"),
    "the owner's policy at L1": l3_budget_policy(id_="pol_l1", level="L1"),
    "the owner's L3 policy with too few credits": l3_budget_policy(id_="pol_small", credits=CAP - 1.0),
    "the owner's L3 policy with no credit bound": l3_budget_policy(id_="pol_unbounded", credits=None),
    "the owner's L3 policy with no daily allowance": l3_budget_policy(id_="pol_nodaily", per_day=None),
}


@pytest.mark.parametrize("label", sorted(NOT_COVERED))
def test_FR_AGT_14_without_a_covering_owner_policy_the_firing_is_skipped_and_retried_next_week(
    rig: SchedApi, label: str
) -> None:
    source = rig.source_run_task()  # the owner approved the source by hand: that approval is NOT a policy
    if NOT_COVERED[label] is not None:
        rig.store.policies[NOT_COVERED[label]["id"]] = NOT_COVERED[label]
    sid = rig.created(source)["schedule_id"]
    compiled = len(rig.rf.compile_calls)

    assert fire(rig) == 0

    record = rig.schedules.get(sid)
    assert rig.worlds_besides(source.world_id) == []  # no world, no events, no run
    assert len(rig.rf.compile_calls) == compiled
    assert (record.failures, record.last_error) == (1, "budget_not_granted")
    assert record.next_due == MON_0330Z + WEEK and record.last_world_id is None and record.last_slot is None
    assert record.backoff_until is not None and record.backoff_until > MON_0330Z

    for step in (timedelta(minutes=1), timedelta(hours=6), timedelta(days=3)):  # not every minute
        assert fire(rig, MON_0330Z + step) == 0
    assert rig.schedules.get(sid).failures == 1
    assert rig.worlds_besides(source.world_id) == []

    if NOT_COVERED[label] is not None:
        del rig.store.policies[NOT_COVERED[label]["id"]]  # the owner replaces the rule that did not cover it
    rig.store.policies[POLICY_ID] = l3_budget_policy()  # the standing rule that does: next week it runs
    assert fire(rig, MON_0330Z + WEEK) == 1
    world_id = world_of(rig, sid)
    wait_for(lambda: rig.events(world_id, "world.started"), what="the run")
    (grant,) = rig.events(world_id, "budget.granted")
    assert (grant["authz"]["by"], grant["authz"]["ref"]) == ("policy", POLICY_ID)
    settled(rig, world_id)


def test_FR_AGT_14_a_policy_with_one_grant_a_day_covers_one_schedule_per_day_across_worlds(rig: SchedApi) -> None:
    source = armed(rig, per_day=1)
    rig.insert(source, "sched_a")
    rig.insert(source, "sched_b")
    assert fire(rig) == 1  # the second one meets the policy's daily allowance, counted over the owner's earlier grants
    assert rig.schedules.get("sched_a").last_world_id
    skipped = rig.schedules.get("sched_b")
    assert (skipped.last_world_id, skipped.failures, skipped.last_error) == (None, 1, "budget_not_granted")
    assert len(rig.worlds_besides(source.world_id)) == 1
    settled(rig, world_of(rig, "sched_a"))


def test_FR_AGT_14_a_person_approval_of_the_source_never_carries_over_a_fired_runs_send_still_needs_a_person(
    rig: SchedApi,
) -> None:
    source = armed(rig)
    cards = rig.rf.cards().json()  # the owner approves the source run's send by hand: it completes
    (gate,) = [c for c in cards if c["kind"] == "gate"]
    assert rig.rf.answer(gate["id"], "approve").status_code == 200
    wait_for(lambda: rig.rf.events("world.completed"), what="the source run to complete")
    sent_by_source = len(rig.rf.adapter.sent)
    assert sent_by_source == 1

    sid = rig.created(source)["schedule_id"]
    assert fire(rig) == 1
    world_id = world_of(rig, sid)
    wait_for(lambda: rig.events(world_id, "approval.requested"), what="the fired run's gate")
    stream = settled(rig, world_id)

    names = {e["type"] for e in stream}
    assert not names & {"approval.resolved", "data.transfer", "artifact.delivered", "world.completed"}, names
    assert len(rig.rf.adapter.sent) == sent_by_source  # nothing went out
    assert not [e for e in stream if (e.get("authz") or {}).get("by") == "person"]  # no person's approval in this world
    assert [e["authz"]["by"] for e in stream if e["type"] == "budget.granted"] == ["policy"]
    assert len([e for e in rig.rf.outbox_store.all_entries() if e["world_id"] == world_id]) == 0

    rig.as_owner_of(world_id)
    cards = rig.flow.client.get(f"/worlds/{world_id}/cards")
    assert cards.status_code == 200
    (card,) = [c for c in cards.json() if c["kind"] == "gate"]  # a card waits for the owner
    answered = rig.flow.client.post(f"/worlds/{world_id}/cards/{card['id']}/answer", json={"option": "approve"})
    assert answered.status_code == 200, answered.text
    wait_for(lambda: rig.events(world_id, "world.completed"), what="the fired run to complete")
    (resolved,) = rig.events(world_id, "approval.resolved")
    assert resolved["authz"]["by"] == "person" and resolved["authz"]["ref"] == FLOW_USER
    assert len(rig.rf.adapter.sent) == sent_by_source + 1


# --- chaining and missed slots ---------------------------------------------------------------------------------------


def test_FR_AGT_14_each_firing_is_offered_the_previous_world_and_never_reuses_it(rig: SchedApi, monkeypatch) -> None:
    from tilo_api import schedules

    source = armed(rig)
    sid = rig.created(source)["schedule_id"]
    seen: list[RunStart] = []
    original = schedules.ScheduleStarter.start

    def spy(self: Any, run: RunStart) -> str:
        seen.append(run)
        return original(self, run)

    monkeypatch.setattr(schedules.ScheduleStarter, "start", spy)
    assert fire(rig) == 1
    first = world_of(rig, sid)
    wait_for(lambda: rig.events(first, "world.started"), what="the first run")
    first_ids = {e["id"] for e in settled(rig, first)}

    assert fire(rig, MON_0330Z + WEEK) == 1
    second = world_of(rig, sid)
    second_stream = settled(rig, second)

    assert [r.prior_world_id for r in seen] == [None, first]
    assert [r.slot for r in seen] == [MON_0330Z, MON_0330Z + WEEK]
    assert second != first and WORLD_ID.match(second)
    assert not first_ids & {e["id"] for e in second_stream}  # offered, never silently reused
    assert rig.schedules.get(sid).last_slot == slot_key(sid, MON_0330Z + WEEK)


def test_FR_AGT_14_missed_slots_collapse_into_one_run_and_one_info_alert_in_its_world(rig: SchedApi, registry) -> None:
    source = armed(rig)
    sid = rig.created(source)["schedule_id"]
    assert fire(rig, MON_0330Z + 3 * WEEK + timedelta(days=2)) == 1
    world_id = world_of(rig, sid)
    stream = settled(rig, world_id)
    assert rig.schedules.get(sid).next_due == MON_0330Z + 4 * WEEK
    assert rig.schedules.get(sid).last_slot.startswith(f"{sid}:")  # (complete() records the claimed slot's key)
    (alert,) = [e for e in stream if e["type"] == "alert.raised"]
    assert alert["severity"] == "info" and alert["data"]["card_id"] is None and "3" in alert["summary"]
    assert_valid_event(REPO_ROOT, registry, alert)
    assert len(rig.worlds_besides(source.world_id)) == 1  # no backfill storm


def test_FR_AGT_14_a_disabled_schedule_never_fires_and_a_deleted_one_is_gone(rig: SchedApi) -> None:
    source = armed(rig)
    sid = rig.created(source)["schedule_id"]
    assert rig.patch(sid, enabled=False).status_code == 200
    assert fire(rig, MON_0330Z + WEEK) == 0
    assert rig.worlds_besides(source.world_id) == []
    assert rig.patch(sid, enabled=True).status_code == 200
    assert rig.delete(sid).status_code == 204
    assert fire(rig, MON_0330Z + 2 * WEEK) == 0
    assert rig.worlds_besides(source.world_id) == []


def test_FR_AGT_14_a_start_of_a_schedule_disabled_after_the_claim_is_skipped_uncounted(rig: SchedApi) -> None:
    """FR-AGT-14d (security review): `ScheduleStarter.start` re-reads `enabled` after the claim. A slot claimed just
    before `disable_for_owner` or a pause must not start a run, and must not count as a failure."""
    from tilo_api import schedules
    from tilo_harness.schedule import StartSkipped

    source = armed(rig)
    sid = rig.created(source)["schedule_id"]
    record = rig.schedules.get(sid)
    starter = schedules.ScheduleStarter(
        store=rig.store,
        schedules=rig.schedules,
        seams=object(),
        clock=rig.clock,  # type: ignore[arg-type]
    )
    assert rig.schedules.disable_for_owner(record.owner_user_id) == 1
    with pytest.raises(StartSkipped) as skipped:
        starter.start(run_start(rig, sid))
    assert (skipped.value.code, skipped.value.count) == ("schedule_disabled", False)
    assert rig.worlds_besides(source.world_id) == []


def test_FR_AGT_14_a_schedule_disabled_between_the_claim_and_the_start_fires_nothing_and_records_nothing(
    rig: SchedApi, monkeypatch
) -> None:
    source = armed(rig)
    sid = rig.created(source)["schedule_id"]
    claim = rig.schedules.claim

    def claim_then_disable(schedule_id: str, due: Any) -> bool:
        won = claim(schedule_id, due)
        if won:
            rig.schedules.update(schedule_id, enabled=False)  # the owner pauses it right after the claim
        return won

    monkeypatch.setattr(rig.schedules, "claim", claim_then_disable)
    assert fire(rig) == 0
    record = rig.schedules.get(sid)
    assert rig.worlds_besides(source.world_id) == []
    assert (record.failures, record.last_error, record.enabled) == (0, None, False)
    assert record.next_due == MON_0330Z
    assert record.backoff_until is None


def test_FR_AGT_14_replay_only_holds_the_slot_and_it_fires_once_when_the_flag_clears(rig: SchedApi) -> None:
    source = armed(rig)
    sid = rig.created(source)["schedule_id"]
    rig.flags.set("replay_only", True, reason="NFR-24 test")
    assert fire(rig, MON_0330Z + 2 * WEEK + timedelta(hours=1)) == 0
    assert rig.worlds_besides(source.world_id) == []
    assert rig.schedules.get(sid).failures == 0 and rig.schedules.get(sid).next_due == MON_0330Z
    rig.flags.set("replay_only", False, reason="cleared")
    assert fire(rig, MON_0330Z + 2 * WEEK + timedelta(hours=2)) == 1
    assert rig.schedules.get(sid).last_slot.startswith(f"{sid}:")
    settled(rig, world_of(rig, sid))


# --- failures: unwired seams, a start that raises, a failing schedule that must not starve another --------------------


def test_FR_AGT_14_with_the_run_seams_unwired_the_firing_is_skipped_without_a_failure_and_retried_next_tick(
    rig: SchedApi,
) -> None:
    """FR-AGT-14d item 3 (changed deliberately from FR-AGT-14b, which pinned `failures == 1` and a backoff here):
    unwired seams are a GLOBAL condition, not this schedule's fault, so nothing is counted against it. The claim is
    released, `failures` stays 0, there is no backoff and the same slot is claimable on the very next tick."""
    from tilo_api import deps

    source = armed(rig)
    sid = rig.created(source)["schedule_id"]

    def unwired() -> Any:
        raise NotImplementedError("no artifact store is configured, so no run starts")

    rig.app.dependency_overrides[deps.get_artifact_store] = unwired
    assert fire(rig) == 0
    record = rig.schedules.get(sid)
    assert rig.worlds_besides(source.world_id) == []
    assert (record.failures, record.last_error, record.next_due) == (0, None, MON_0330Z)
    assert record.backoff_until is None  # no backoff
    assert record.enabled is True
    assert fire(rig, MON_0330Z + timedelta(seconds=30)) == 0  # still unwired: tried again, nothing counted
    assert (rig.schedules.get(sid).failures, rig.schedules.get(sid).backoff_until) == (0, None)

    rig.app.dependency_overrides[deps.get_artifact_store] = lambda: rig.rf.rig.store  # wired again
    assert fire(rig, MON_0330Z + timedelta(seconds=60)) == 1  # the slot was claimable at once: no backoff to wait out
    assert rig.schedules.get(sid).last_slot == slot_key(sid, MON_0330Z)  # the same slot, not a later one
    settled(rig, world_of(rig, sid))


def test_FR_AGT_14_a_run_that_cannot_start_releases_the_claim_backs_off_and_leaves_one_world_on_retry(
    rig: SchedApi, monkeypatch
) -> None:
    from tilo_api import runs

    source = armed(rig)
    sid = rig.created(source)["schedule_id"]
    original, calls = runs.start_run, []

    def flaky(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("scheduler says: api key s3cret-value for alice@example.com is invalid")
        return original(*args, **kwargs)

    monkeypatch.setattr(runs, "start_run", flaky)
    rig.clock.set(MON_0330Z)
    response = rig.tick()
    assert response.status_code == 200 and response.json() == {"fired": 0}
    for leaked in ("s3cret", "alice", "scheduler says"):
        assert leaked not in response.text
    record = rig.schedules.get(sid)
    assert (record.failures, record.next_due, record.last_slot) == (1, MON_0330Z, None)
    assert CODE.match(record.last_error) and "s3cret" not in record.last_error  # a fixed code, never the text
    assert record.backoff_until > MON_0330Z
    assert fire(rig, MON_0330Z + timedelta(seconds=10)) == 0  # backed off
    assert len(calls) == 1

    assert fire(rig, record.backoff_until) == 1  # the claim was released: the same slot starts
    world_id = world_of(rig, sid)
    wait_for(lambda: rig.events(world_id, "world.started"), what="the retried run")
    settled(rig, world_id)
    assert rig.worlds_besides(source.world_id) == [world_id]  # whatever the failed attempt made is this very world
    for once in ("world.requested", "budget.granted", "world.started"):
        assert types(rig, world_id).count(once) == 1, once
    assert rig.schedules.get(sid).last_slot == slot_key(sid, MON_0330Z)


def test_FR_AGT_14_twenty_failing_schedules_do_not_starve_a_healthy_twenty_first(rig: SchedApi, monkeypatch) -> None:
    from tilo_api import runs

    source = armed(rig)
    rig.store.policies["pol_bad"] = l3_budget_policy("u_bad", id_="pol_bad", per_day=500)
    rig.store.policies[POLICY_ID] = l3_budget_policy(per_day=500)
    original = runs.start_run

    def selective(store: Any, task: Any, **kwargs: Any) -> Any:
        if task.owner == "u_bad":
            raise RuntimeError("this owner's runs cannot start")
        return original(store, task, **kwargs)

    monkeypatch.setattr(runs, "start_run", selective)
    for n in range(20):  # older than the healthy one, so they sort first
        rig.insert(source, f"sched_bad{n:02d}", owner_user_id="u_bad", next_due=MON_0330Z - WEEK)
    rig.insert(source, "sched_good")

    assert fire(rig) == 0  # the rate limit: 20 attempts, all failing
    assert rig.schedules.get("sched_good").last_world_id is None
    assert fire(rig, MON_0330Z + timedelta(seconds=30)) == 1  # the 20 are backed off: the healthy one runs now
    world_id = world_of(rig, "sched_good")
    wait_for(lambda: rig.events(world_id, "world.started"), what="the healthy run")
    settled(rig, world_id)
    assert all(rig.schedules.get(f"sched_bad{n:02d}").failures == 1 for n in range(20))  # none was retried meanwhile
