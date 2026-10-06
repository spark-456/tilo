"""FR-AGT-14b (PRD 6.3, 8.6; design: scratchpad fr-agt-14b-design.md decisions 5 and 6): the production schedule store.

One conformance suite, run against the in-memory store always and against the Firestore store under
`-m emulator` (the `firestore` param below carries the `emulator` mark, so the default run skips it). The cases:

- the four `ScheduleStore` calls of PR #446 keep their meaning (claim is an atomic compare-and-set, release drops only
  the claim it was asked to, complete is the only call that moves `next_due`);
- a claim is a lease of `CLAIM_LEASE` measured on the STORE's clock, never the caller's (memory store only: Firestore
  uses server time, which a test cannot move);
- `due` returns enabled, due, not-backed-off records oldest first (ties by id); a record that cannot be built is
  quarantined (`enabled=False`, `last_error="invalid_record"`) and skipped, and `due` never raises for one;
- failures back off (`record_failure`, `backoff_for`), never starve a healthy schedule behind 20 failing ones, and
  disable the schedule after `MAX_FAILURES`;
- schedule ids cannot reach a Firestore path; the owner cap is atomic.

`open_schedule_store` is the one explicit-config door to Firestore (ADR-0003 addendum): with no config it refuses and
never builds a client. Interface: services/api/tests/API_FR_AGT_14b.md. Fakes: fr_agt_14_store_support.py.
"""

from __future__ import annotations

import math
import threading
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest
from fr_agt_14_store_support import (
    MON_0330Z,
    OWNER,
    WEEK,
    StoreRig,
    firestore_rig,
    make_record,
    memory_rig,
)
from tilo_harness.schedule import CLAIM_LEASE, Cadence, slot_key
from tilo_harness.schedule_store import (
    MAX_FAILURES,
    InMemoryScheduleStore,
    ScheduleStoreNotConfigured,
    backoff_for,
    open_schedule_store,
    schedule_from_doc,
    schedule_to_doc,
)

DUE = MON_0330Z


@pytest.fixture(params=["memory", pytest.param("firestore", marks=pytest.mark.emulator)])
def rig(request: pytest.FixtureRequest) -> StoreRig:
    if request.param == "memory":
        return memory_rig()
    request.getfixturevalue("emulator_host")
    return firestore_rig()


@pytest.fixture
def mem() -> StoreRig:
    return memory_rig()


def _ids(schedules: list[Any]) -> list[str]:
    return [s.schedule_id for s in schedules]


# --- create / read / update / delete --------------------------------------------------------------------------------


def test_FR_AGT_14_store_create_round_trips_every_field_of_the_snapshot(rig: StoreRig) -> None:
    schedule = make_record(
        "sched_a",
        title="Friday digest",
        budget_cap=55.5,
        last_world_id="w_prev",
        last_slot="sched_a:2026-09-28T03:30:00+00:00",
    )
    assert rig.store.create(schedule, max_per_owner=10) is True
    got = rig.store.get("sched_a")
    assert got is not None
    for name in (
        "schedule_id",
        "owner_user_id",
        "title",
        "cadence",
        "approved_brief_ref",
        "budget_cap",
        "enabled",
        "next_due",
        "last_slot",
        "last_world_id",
        "brief",
        "approach",
        "created_at",
    ):
        assert getattr(got, name) == getattr(schedule, name), name
    assert (got.failures, got.backoff_until, got.last_error) == (0, None, None)
    assert rig.store.get("sched_missing") is None


def test_FR_AGT_14_store_the_snapshot_is_a_copy_in_and_out(rig: StoreRig) -> None:
    brief = {"goal": "original goal", "deliverables": [{"title": "T", "format": "pdf"}]}
    rig.store.create(make_record("sched_a", brief=brief), max_per_owner=10)
    brief["goal"] = "changed after create"
    brief["deliverables"].append({"title": "extra", "format": "pdf"})
    first = rig.store.get("sched_a")
    assert first.brief == {"goal": "original goal", "deliverables": [{"title": "T", "format": "pdf"}]}
    first.brief["goal"] = "changed after read"
    assert rig.store.get("sched_a").brief["goal"] == "original goal"


def test_FR_AGT_14_store_the_owner_cap_is_enforced_per_owner_and_refusal_stores_nothing(rig: StoreRig) -> None:
    assert rig.store.create(make_record("sched_1"), max_per_owner=2) is True
    assert rig.store.create(make_record("sched_2"), max_per_owner=2) is True
    assert rig.store.create(make_record("sched_3"), max_per_owner=2) is False
    assert rig.store.get("sched_3") is None
    assert _ids(rig.store.list_for_owner(OWNER)) and len(rig.store.list_for_owner(OWNER)) == 2
    assert rig.store.create(make_record("sched_4", owner_user_id="u_other"), max_per_owner=2) is True
    assert rig.store.delete("sched_1") is True  # room again
    assert rig.store.create(make_record("sched_5"), max_per_owner=2) is True


def test_FR_AGT_14_store_the_owner_cap_holds_under_concurrent_creates(rig: StoreRig) -> None:
    results: list[bool] = []
    barrier = threading.Barrier(12)
    lock = threading.Lock()

    def worker(n: int) -> None:
        barrier.wait(timeout=10)
        won = rig.store.create(make_record(f"sched_c{n:02d}"), max_per_owner=3)
        with lock:
            results.append(won)

    threads = [threading.Thread(target=worker, args=(n,), daemon=True) for n in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert results.count(True) == 3, results
    assert len(rig.store.list_for_owner(OWNER)) == 3


def test_FR_AGT_14_store_list_for_owner_returns_only_that_owners_schedules(rig: StoreRig) -> None:
    rig.add(
        make_record("sched_mine1"),
        make_record("sched_mine2"),
        make_record("sched_theirs", owner_user_id="u_other"),
    )
    assert sorted(_ids(rig.store.list_for_owner(OWNER))) == ["sched_mine1", "sched_mine2"]
    assert _ids(rig.store.list_for_owner("u_other")) == ["sched_theirs"]
    assert rig.store.list_for_owner("u_nobody") == []


def test_FR_AGT_14_store_update_changes_only_the_fields_it_is_given(rig: StoreRig) -> None:
    rig.add(make_record("sched_a"))
    new_cadence = Cadence(weekday=4, hour=17, minute=30, tz="Europe/London")
    new_due = datetime(2026, 10, 9, 16, 30, tzinfo=UTC)  # Friday 17:30 BST
    updated = rig.store.update("sched_a", enabled=False, title="Friday report", cadence=new_cadence, next_due=new_due)
    assert updated is not None and updated.title == "Friday report" and updated.enabled is False
    got = rig.store.get("sched_a")
    assert (got.title, got.enabled, got.cadence, got.next_due) == ("Friday report", False, new_cadence, new_due)
    original = make_record("sched_a")
    for kept in ("owner_user_id", "budget_cap", "brief", "approach", "approved_brief_ref", "last_slot"):
        assert getattr(got, kept) == getattr(original, kept), kept
    assert rig.store.update("sched_missing", enabled=True) is None
    only_title = rig.store.update("sched_a", title="Again")
    assert only_title.enabled is False and only_title.cadence == new_cadence  # None means unchanged


def test_FR_AGT_14_store_delete_removes_the_schedule_once(rig: StoreRig) -> None:
    rig.add(make_record("sched_a"))
    assert rig.store.delete("sched_a") is True
    assert rig.store.get("sched_a") is None
    assert rig.store.delete("sched_a") is False
    assert rig.store.due(DUE + WEEK, 20) == []


@pytest.mark.parametrize(
    "bad_id", ["", "a/b", "sched_a/b", "..", "sched_..", "sched_a b", "sched_" + "x" * 80, "w_world"]
)
def test_FR_AGT_14_store_a_schedule_id_can_never_become_a_path(rig: StoreRig, bad_id: str) -> None:
    with pytest.raises(ValueError):
        rig.store.create(make_record(bad_id), max_per_owner=10)
    assert rig.store.get(bad_id) is None  # a lookup of a bad id is "not found", never a raise or a path
    assert rig.store.claim(bad_id, DUE) is False
    assert rig.store.delete(bad_id) is False


# --- due ------------------------------------------------------------------------------------------------------------


def test_FR_AGT_14_store_due_returns_only_enabled_due_schedules_and_includes_the_boundary(rig: StoreRig) -> None:
    rig.add(
        make_record("sched_due"),
        make_record("sched_later", next_due=DUE + WEEK),
        make_record("sched_off", enabled=False),
        make_record("sched_old", next_due=DUE - 2 * WEEK),
    )
    assert _ids(rig.store.due(DUE, 20)) == ["sched_old", "sched_due"]
    assert _ids(rig.store.due(DUE - timedelta(microseconds=1), 20)) == ["sched_old"]
    assert _ids(rig.store.due(DUE + WEEK, 20)) == ["sched_old", "sched_due", "sched_later"]


def test_FR_AGT_14_store_due_is_oldest_first_ties_by_id_and_honours_the_limit(rig: StoreRig) -> None:
    rig.add(
        make_record("sched_b"),
        make_record("sched_a"),
        make_record("sched_z", next_due=DUE - 3 * WEEK),
        make_record("sched_m", next_due=DUE - WEEK),
    )
    assert _ids(rig.store.due(DUE, 20)) == ["sched_z", "sched_m", "sched_a", "sched_b"]
    assert _ids(rig.store.due(DUE, 2)) == ["sched_z", "sched_m"]
    assert rig.store.due(DUE, 0) == []


def test_FR_AGT_14_store_due_leaves_a_backed_off_schedule_out_until_its_backoff_has_passed(rig: StoreRig) -> None:
    rig.add(
        make_record("sched_wait", failures=2, backoff_until=DUE + timedelta(seconds=1), last_error="start_failed"),
        make_record("sched_edge", failures=2, backoff_until=DUE, last_error="start_failed"),
        make_record("sched_past", failures=2, backoff_until=DUE - timedelta(hours=1), last_error="start_failed"),
    )
    assert _ids(rig.store.due(DUE, 20)) == ["sched_edge", "sched_past"]
    assert _ids(rig.store.due(DUE + timedelta(seconds=1), 20)) == ["sched_edge", "sched_past", "sched_wait"]


# --- quarantine ------------------------------------------------------------------------------------------------------

_GOOD = schedule_to_doc(make_record("sched_x"))


def _bad_docs() -> dict[str, dict[str, Any]]:
    misaligned = DUE + timedelta(minutes=1)
    return {
        "misaligned_next_due": {"next_due": misaligned},
        "off_weekday_next_due": {"next_due": DUE + timedelta(days=1)},
        "next_due_not_a_datetime": {"next_due": "2026-10-05T03:30:00Z"},
        "next_due_missing": {"next_due": None},
        "cap_zero": {"budget_cap": 0},
        "cap_negative": {"budget_cap": -5.0},
        "cap_nan": {"budget_cap": math.nan},
        "cap_infinite": {"budget_cap": math.inf},
        "cap_string": {"budget_cap": "40"},
        "cap_bool": {"budget_cap": True},
        "cadence_unknown_zone": {"cadence": {"weekday": 0, "hour": 9, "minute": 0, "tz": "Mars/Olympus"}},
        "cadence_hour_25": {"cadence": {"weekday": 0, "hour": 25, "minute": 0, "tz": "Asia/Kolkata"}},
        "cadence_weekday_name": {"cadence": {"weekday": "mon", "hour": 9, "minute": 0, "tz": "Asia/Kolkata"}},
        "cadence_missing_field": {"cadence": {"weekday": 0, "hour": 9}},
        "cadence_not_a_dict": {"cadence": "weekly"},
        "owner_not_a_string": {"owner_user_id": 5},
        "title_not_a_string": {"title": ["x"]},
        "brief_not_a_dict": {"brief": "text"},
    }


BAD_DOCS = _bad_docs()


def _bad(schedule_id: str, name: str) -> dict[str, Any]:
    return {**schedule_to_doc(make_record(schedule_id)), **BAD_DOCS[name]}


def test_FR_AGT_14_store_a_valid_document_round_trips_through_the_doc_functions() -> None:
    schedule = make_record(
        "sched_a", failures=3, backoff_until=DUE + timedelta(minutes=8), last_error="start_failed", last_world_id="w_1"
    )
    assert schedule_from_doc(schedule_to_doc(schedule)) == schedule
    assert schedule_to_doc(schedule)["next_due"] == DUE


@pytest.mark.parametrize("name", sorted(BAD_DOCS))
def test_FR_AGT_14_store_a_document_that_cannot_be_built_is_refused_by_the_doc_reader(name: str) -> None:
    with pytest.raises(ValueError):
        schedule_from_doc(_bad("sched_x", name))


def test_FR_AGT_14_store_a_naive_next_due_cannot_be_built_either() -> None:
    naive = DUE.replace(tzinfo=None)
    with pytest.raises(ValueError):
        schedule_from_doc({**schedule_to_doc(make_record("sched_x")), "next_due": naive})


@pytest.mark.parametrize("name", sorted(BAD_DOCS))
def test_FR_AGT_14_store_due_quarantines_a_bad_record_and_skips_it_without_raising(rig: StoreRig, name: str) -> None:
    rig.add(make_record("sched_good", next_due=DUE))
    rig.store.insert_raw(_bad("sched_bad", name))

    assert _ids(rig.store.due(DUE + WEEK, 20)) == ["sched_good"]  # never raised out of due()

    doc = rig.store.read_doc("sched_bad")
    assert doc["enabled"] is False and doc["last_error"] == "invalid_record", doc
    assert rig.store.claim("sched_bad", DUE) is False
    assert _ids(rig.store.due(DUE + WEEK, 20)) == ["sched_good"]  # and again: nothing is re-processed or raised


def test_FR_AGT_14_store_due_quarantines_a_naive_next_due_without_raising(mem: StoreRig) -> None:
    mem.add(make_record("sched_good"))
    mem.store.insert_raw({**schedule_to_doc(make_record("sched_bad")), "next_due": DUE.replace(tzinfo=None)})
    assert _ids(mem.store.due(DUE, 20)) == ["sched_good"]
    assert mem.store.read_doc("sched_bad")["last_error"] == "invalid_record"


def test_FR_AGT_14_store_a_due_record_with_almost_nothing_else_is_quarantined(rig: StoreRig) -> None:
    rig.store.insert_raw({"schedule_id": "sched_empty", "enabled": True, "next_due": DUE})
    rig.add(make_record("sched_good"))
    assert _ids(rig.store.due(DUE, 20)) == ["sched_good"]
    assert rig.store.read_doc("sched_empty")["enabled"] is False


def test_FR_AGT_14_store_a_flood_of_bad_records_cannot_hide_a_healthy_schedule(rig: StoreRig) -> None:
    """25 corrupt records sort before the healthy one: a tick that reads the oldest 20 meets only quarantine. Within one
    more call the healthy schedule is returned."""
    for n in range(25):
        rig.store.insert_raw(
            {**schedule_to_doc(make_record(f"sched_bad{n:02d}")), "next_due": DUE - WEEK + timedelta(minutes=1)}
        )
    rig.add(make_record("sched_healthy"))
    seen = _ids(rig.store.due(DUE, 20))
    if "sched_healthy" not in seen:
        seen = _ids(rig.store.due(DUE, 20))
    assert seen == ["sched_healthy"]


# --- claim, release, complete ---------------------------------------------------------------------------------------


def test_FR_AGT_14_store_claim_is_a_compare_and_set_on_next_due(rig: StoreRig) -> None:
    rig.add(make_record("sched_a"), make_record("sched_off", enabled=False))
    assert rig.store.claim("sched_a", DUE + WEEK) is False  # not its next_due
    assert rig.store.claim("sched_a", DUE - WEEK) is False
    assert rig.store.claim("sched_a", DUE) is True
    assert rig.store.claim("sched_a", DUE) is False  # held
    assert rig.store.claim("sched_off", DUE) is False  # disabled
    assert rig.store.claim("sched_missing", DUE) is False


def test_FR_AGT_14_store_release_drops_only_the_claim_it_was_asked_to_and_changes_nothing_else(rig: StoreRig) -> None:
    rig.add(make_record("sched_a"))
    before = rig.store.get("sched_a")
    assert rig.store.claim("sched_a", DUE) is True
    rig.store.release("sched_a", DUE + WEEK)  # another due: not this claim
    assert rig.store.claim("sched_a", DUE) is False
    rig.store.release("sched_missing", DUE)  # never raises
    rig.store.release("sched_a", DUE)
    assert rig.store.get("sched_a") == before
    assert rig.store.claim("sched_a", DUE) is True


def test_FR_AGT_14_store_complete_moves_next_due_and_drops_the_claim(rig: StoreRig) -> None:
    rig.add(make_record("sched_a"))
    assert rig.store.claim("sched_a", DUE)
    rig.store.complete("sched_a", DUE, next_due=DUE + WEEK, last_world_id="w_run_1")
    got = rig.store.get("sched_a")
    assert (got.next_due, got.last_slot, got.last_world_id) == (DUE + WEEK, slot_key("sched_a", DUE), "w_run_1")
    assert rig.store.claim("sched_a", DUE) is False  # the old slot is gone for good
    assert rig.store.claim("sched_a", DUE + WEEK) is True  # and the new one is claimable (no leftover claim)
    assert rig.store.due(DUE, 20) == []


def test_FR_AGT_14_store_only_one_of_many_concurrent_claimers_wins(rig: StoreRig) -> None:
    rig.add(make_record("sched_a"))
    wins: list[bool] = []
    barrier, lock = threading.Barrier(16), threading.Lock()

    def worker() -> None:
        barrier.wait(timeout=10)
        won = rig.store.claim("sched_a", DUE)
        with lock:
            wins.append(won)

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert wins.count(True) == 1 and len(wins) == 16


# --- the lease runs on the store's clock -----------------------------------------------------------------------------


def test_FR_AGT_14_store_a_claim_is_a_lease_measured_on_the_stores_own_clock(mem: StoreRig) -> None:
    assert CLAIM_LEASE == timedelta(minutes=5)
    mem.add(make_record("sched_a"))
    assert mem.store.claim("sched_a", DUE) is True
    mem.clock.advance(CLAIM_LEASE - timedelta(seconds=1))
    assert mem.store.claim("sched_a", DUE) is False  # still live
    mem.clock.advance(timedelta(seconds=2))
    assert mem.store.claim("sched_a", DUE) is True  # stale: a crashed holder's slot is claimable again
    assert mem.store.claim("sched_a", DUE) is False  # and the new claim is a fresh lease


def test_FR_AGT_14_store_a_callers_clock_cannot_age_a_lease(mem: StoreRig) -> None:
    """`due(now, ...)` takes the CALLER's now. A caller that jumps its own clock a year ahead must not make a live
    claim look stale: only the store's clock decides."""
    mem.add(make_record("sched_a"))
    assert mem.store.claim("sched_a", DUE)
    mem.store.due(DUE + 365 * WEEK, 20)
    mem.store.due(datetime(2099, 1, 1, tzinfo=UTC), 20)
    assert mem.store.claim("sched_a", DUE) is False
    mem.clock.advance(CLAIM_LEASE + timedelta(seconds=1))
    assert mem.store.claim("sched_a", DUE) is True


def test_FR_AGT_14_store_a_released_claim_is_free_at_once_without_waiting_for_the_lease(mem: StoreRig) -> None:
    mem.add(make_record("sched_a"))
    mem.store.claim("sched_a", DUE)
    mem.store.release("sched_a", DUE)
    assert mem.store.claim("sched_a", DUE) is True


def test_FR_AGT_14_store_the_stores_clock_defaults_to_the_wall_clock() -> None:
    store = InMemoryScheduleStore()
    store.create(make_record("sched_a"), max_per_owner=10)
    assert store.claim("sched_a", DUE) is True
    assert store.claim("sched_a", DUE) is False  # a lease on real time: live for the next 5 minutes


# --- failures: backoff, quarantine of the repeat offender, starvation ------------------------------------------------


def test_FR_AGT_14_store_backoff_for_grows_is_capped_at_a_day_and_never_overflows() -> None:
    assert MAX_FAILURES == 8
    assert timedelta(seconds=60) <= backoff_for(1) <= timedelta(seconds=120)
    previous = timedelta(0)
    for failures in range(1, 60):
        wait = backoff_for(failures)
        assert previous <= wait <= timedelta(hours=24), failures
        previous = wait
    assert backoff_for(60) == timedelta(hours=24)
    assert backoff_for(10**6) == timedelta(hours=24)  # no OverflowError, no giant integer


def test_FR_AGT_14_store_a_failed_start_counts_backs_off_and_frees_the_claim(rig: StoreRig) -> None:
    rig.add(make_record("sched_a"))
    assert rig.store.claim("sched_a", DUE)
    rig.store.record_failure("sched_a", DUE, error="start_failed")
    doc = rig.store.read_doc("sched_a")
    assert (doc["failures"], doc["last_error"], doc["enabled"], doc["next_due"]) == (1, "start_failed", True, DUE)
    wait = doc["backoff_until"] - rig.now()
    assert timedelta(seconds=50) <= wait <= timedelta(hours=24, minutes=1), wait
    assert rig.store.due(DUE, 20) == []  # backed off
    assert _ids(rig.store.due(doc["backoff_until"], 20)) == ["sched_a"]  # and back when the backoff has passed
    if rig.is_memory:  # the claim was dropped by record_failure: nothing waits for the lease
        rig.clock.set(doc["backoff_until"])
        assert rig.store.claim("sched_a", DUE) is True


def test_FR_AGT_14_store_a_skipped_slot_can_move_next_due_in_the_same_write(rig: StoreRig) -> None:
    rig.add(make_record("sched_a"))
    assert rig.store.claim("sched_a", DUE)
    rig.store.record_failure("sched_a", DUE, error="budget_not_granted", next_due=DUE + WEEK)
    got = rig.store.get("sched_a")
    assert (got.next_due, got.failures, got.last_error) == (DUE + WEEK, 1, "budget_not_granted")
    assert got.last_slot is None and got.last_world_id is None  # nothing ran
    assert rig.store.claim("sched_a", DUE) is False  # the old slot is gone


def test_FR_AGT_14e_store_record_refusal_sets_only_last_error(rig: StoreRig) -> None:
    """FR-AGT-14e (BQ-AGT14-5 R3): a permanent refusal of a delivered task is recorded as a fixed code and nothing else:
    not a failure (no count, no backoff, no disabling), the slot and the claim are untouched."""
    rig.add(make_record("sched_a"))
    before = rig.store.read_doc("sched_a")
    rig.store.record_refusal("sched_a", "budget_not_granted")
    after = rig.store.read_doc("sched_a")
    assert after["last_error"] == "budget_not_granted"
    assert {k: v for k, v in after.items() if k != "last_error"} == {
        k: v for k, v in before.items() if k != "last_error"
    }
    assert (after["failures"], after["backoff_until"], after["enabled"], after["next_due"]) == (0, None, True, DUE)
    assert _ids(rig.store.due(DUE, 20)) == ["sched_a"]  # still due: a refusal parks nothing


def test_FR_AGT_14e_store_record_refusal_leaves_a_held_claim_and_a_slot_that_moved_alone(rig: StoreRig) -> None:
    rig.add(make_record("sched_a"))
    assert rig.store.claim("sched_a", DUE)
    rig.store.record_refusal("sched_a", "owner_mismatch")
    assert rig.store.claim("sched_a", DUE) is False  # the claim is still held
    rig.store.complete("sched_a", DUE, next_due=DUE + WEEK, last_world_id="w_run_1")
    got = rig.store.get("sched_a")
    assert (got.next_due, got.last_error) == (DUE + WEEK, None)  # the next completion clears the code, as it clears any
    rig.store.record_refusal("sched_a", "snapshot_missing")
    got = rig.store.get("sched_a")
    assert (got.next_due, got.last_slot, got.last_world_id, got.last_error) == (
        DUE + WEEK,
        slot_key("sched_a", DUE),
        "w_run_1",
        "snapshot_missing",
    )


@pytest.mark.parametrize("bad_id", ["sched_missing", "", "a/b", "..", "sched_a b", "w_world"])
def test_FR_AGT_14e_store_record_refusal_for_an_unknown_or_bad_id_is_a_no_op(rig: StoreRig, bad_id: str) -> None:
    rig.add(make_record("sched_a"))
    before = rig.store.documents()
    rig.store.record_refusal(bad_id, "budget_not_granted")  # never raises, never creates a record, never a path
    assert rig.store.documents() == before
    assert rig.store.get(bad_id) is None


@pytest.mark.parametrize("code", ["Not A Code", "budget not granted", "", "x" * 200, "1abc", "a/b", "café"])
def test_FR_AGT_14e_store_record_refusal_stores_only_a_fixed_code(rig: StoreRig, code: str) -> None:
    """Checked like every other fixed code (`record_failure`): free text never lands in `last_error`."""
    rig.add(make_record("sched_a"))
    rig.store.record_refusal("sched_a", code)
    assert rig.store.read_doc("sched_a")["last_error"] == "start_failed"


def test_FR_AGT_14_store_backoff_doubles_on_each_failure_and_the_schedule_is_disabled_after_the_limit(
    mem: StoreRig,
) -> None:
    mem.add(make_record("sched_a"))
    previous = timedelta(0)
    for failures in range(1, MAX_FAILURES + 1):
        assert mem.store.claim("sched_a", DUE), failures
        mem.store.record_failure("sched_a", DUE, error="start_failed")
        doc = mem.store.read_doc("sched_a")
        assert doc["failures"] == failures
        if failures < MAX_FAILURES:
            assert doc["enabled"] is True
            wait = doc["backoff_until"] - mem.clock()
            assert previous < wait <= timedelta(hours=24), (failures, wait)
            assert wait == backoff_for(failures)
            previous = wait
            mem.clock.set(doc["backoff_until"])  # the backoff passes; the same slot is due again
            assert _ids(mem.store.due(mem.clock(), 20)) == ["sched_a"]
    assert doc["enabled"] is False and isinstance(doc["last_error"], str) and doc["last_error"]
    mem.clock.advance(100 * WEEK)
    assert mem.store.due(mem.clock() + 100 * WEEK, 20) == []
    assert mem.store.claim("sched_a", DUE) is False


def test_FR_AGT_14_store_twenty_failing_schedules_never_starve_the_twenty_first(rig: StoreRig) -> None:
    for n in range(20):
        rig.add(make_record(f"sched_f{n:02d}", next_due=DUE - WEEK))  # older than the healthy one: they sort first
    rig.add(make_record("sched_healthy", next_due=DUE))
    first = rig.store.due(DUE, 20)
    assert len(first) == 20 and "sched_healthy" not in _ids(first)  # the rate limit alone starves it today
    for schedule in first:
        assert rig.store.claim(schedule.schedule_id, DUE - WEEK)
        rig.store.record_failure(schedule.schedule_id, DUE - WEEK, error="start_failed")
    assert _ids(rig.store.due(DUE, 20)) == ["sched_healthy"]


# --- the explicit-config door to Firestore (ADR-0003 addendum) -----------------------------------------------------


class _Bomb:
    """Stands in for `google.cloud.firestore.Client`: any construction is a live client being opened."""

    def __init__(self) -> None:
        self.built: list[tuple[Any, Any]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.built.append((args, kwargs))
        raise AssertionError("a live Firestore client was opened without explicit config")


@pytest.fixture
def no_live_client(monkeypatch: pytest.MonkeyPatch) -> _Bomb:
    from google.cloud import firestore

    bomb = _Bomb()
    monkeypatch.setattr(firestore, "Client", bomb)
    for name in ("FIRESTORE_EMULATOR_HOST", "TILO_SCHEDULES_STORE", "TILO_FIRESTORE_PROJECT"):
        monkeypatch.delenv(name, raising=False)
    return bomb


@pytest.mark.parametrize(
    "env",
    [
        {},
        {"TILO_SCHEDULES_STORE": ""},
        {"TILO_SCHEDULES_STORE": "firestore"},  # no project
        {"TILO_SCHEDULES_STORE": "firestore", "TILO_FIRESTORE_PROJECT": ""},
        {"TILO_FIRESTORE_PROJECT": "demo-tilo"},  # a project without the switch
        {"TILO_SCHEDULES_STORE": "redis"},
        {"TILO_SCHEDULES_STORE": "firestore", "TILO_FIRESTORE_PROJECT": "a/b"},
        {"TILO_SCHEDULES_STORE": "firestore", "TILO_FIRESTORE_PROJECT": "../other"},
        {"TILO_SCHEDULES_STORE": "firestore", "TILO_FIRESTORE_PROJECT": "Has Space"},
        {"TILO_SCHEDULES_STORE": "firestore", "TILO_FIRESTORE_PROJECT": "x"},
        {"TILO_SCHEDULES_STORE": "firestore", "TILO_FIRESTORE_PROJECT": "p" * 80},
    ],
)
def test_FR_AGT_14_store_without_explicit_config_it_refuses_and_opens_no_client(
    no_live_client: _Bomb, env: dict[str, str]
) -> None:
    factory_calls: list[str] = []

    def factory(project: str) -> Any:
        factory_calls.append(project)
        return MagicMock()

    with pytest.raises(ScheduleStoreNotConfigured):
        open_schedule_store(env, firestore_client_factory=factory)
    assert factory_calls == [] and no_live_client.built == []


def test_FR_AGT_14_store_an_unconfigured_process_environment_refuses_too(no_live_client: _Bomb) -> None:
    with pytest.raises(ScheduleStoreNotConfigured):
        open_schedule_store()  # reads os.environ, which the fixture cleared
    assert no_live_client.built == []


def test_FR_AGT_14_store_memory_is_chosen_only_by_name(no_live_client: _Bomb) -> None:
    store = open_schedule_store({"TILO_SCHEDULES_STORE": "memory"})
    assert isinstance(store, InMemoryScheduleStore)
    assert no_live_client.built == []


def test_FR_AGT_14_store_firestore_opens_only_with_the_switch_and_a_valid_project_and_uses_that_project(
    no_live_client: _Bomb,
) -> None:
    from tilo_harness.schedule_store import FirestoreScheduleStore

    calls: list[str] = []

    def factory(project: str) -> Any:
        calls.append(project)
        return MagicMock()

    store = open_schedule_store(
        {"TILO_SCHEDULES_STORE": "firestore", "TILO_FIRESTORE_PROJECT": "demo-tilo"}, firestore_client_factory=factory
    )
    assert isinstance(store, FirestoreScheduleStore)
    assert calls == ["demo-tilo"]
    assert no_live_client.built == []  # the injected factory was used, not the real client


def test_FR_AGT_14_store_the_existing_firestore_store_guard_is_not_loosened(no_live_client: _Bomb) -> None:
    from tilo_harness.store import FirestoreStore

    with pytest.raises(Exception):  # noqa: B017 - the guard's type is unspecified (PRD 15.3 tests)
        FirestoreStore(project_id="demo-tilo")  # no FIRESTORE_EMULATOR_HOST: still refuses, schedule config or not
    assert no_live_client.built == []
