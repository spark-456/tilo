"""FR-AGT-14d item 2 (security follow-up; FR-MEM-09 has no endpoint yet, so this is the adapter, not a trigger).

When a person is erased or loses access, their schedules must stop firing and must go. Two pieces, both on the schedule
stores of `tilo_harness.schedule_store`:

- `disable_for_owner(owner_user_id) -> int` on BOTH stores: sets `enabled=False` and `last_error="owner_disabled"` on
  every schedule of that one owner and returns how many it changed; never touches another owner; an invalid owner id
  (anything but `u_<letters, digits, _>`: blank, wildcard, path-like, not a string) changes nothing. A disabled owner's
  schedules never fire.
- `ScheduleRetention(store)`: a `tilo_memory.retention.RetentionStore` over a schedule store (tilo-harness already
  depends on tilo-memory), so a registry's `firestore` entry can hold `orgs/*/schedules`. `records()` yields every
  document of
  the store with `record_id == schedule_id` and the owner as `user_id`; `delete(record_id)` deletes the document and is
  idempotent. `erase_user` + `verify_erasure` over a registry holding it report nothing remaining, and only the erased
  user's schedules go.

Memory store always, Firestore store under `-m emulator`. Interface: services/api/tests/API_FR_AGT_14d.md.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fr_agt_14_store_support import (
    MON_0330Z,
    OWNER,
    WEEK,
    StoreRig,
    firestore_rig,
    make_record,
    make_tick_rig,
    memory_rig,
)
from tilo_harness import schedule_store as store_module
from tilo_memory.erasure import REQUIRED_STORES, erase_user, request_erasure, verify_erasure
from tilo_memory.retention import RetentionStore

OTHER = "u_other"
NOW = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)


@pytest.fixture(params=["memory", pytest.param("firestore", marks=pytest.mark.emulator)])
def rig(request: pytest.FixtureRequest) -> StoreRig:
    if request.param == "memory":
        return memory_rig()
    request.getfixturevalue("emulator_host")
    return firestore_rig()


def _two_owners(rig: StoreRig) -> None:
    rig.add(
        make_record("sched_a1"),
        make_record("sched_a2", next_due=MON_0330Z + WEEK),
        make_record("sched_b1", owner_user_id=OTHER),
    )


class _Empty:
    """A store holding nothing: the other required stores of a registry."""

    def records(self) -> list[Any]:
        return []

    def delete(self, record_id: str) -> None:
        raise AssertionError(f"nothing to delete here, got {record_id!r}")


def _retention(store: Any) -> Any:
    """`ScheduleRetention(store)`, looked up when called so a missing class fails only the tests that need it."""
    return store_module.ScheduleRetention(store)


def _registry(schedules: RetentionStore) -> dict[str, RetentionStore]:
    return {name: (schedules if name == "firestore" else _Empty()) for name in REQUIRED_STORES}


# --- disable_for_owner ----------------------------------------------------------------------------------------------


def test_FR_AGT_14_disable_for_owner_disables_only_that_owners_schedules_and_counts_them(rig: StoreRig) -> None:
    _two_owners(rig)
    assert rig.store.disable_for_owner(OWNER) == 2
    for schedule_id in ("sched_a1", "sched_a2"):
        got = rig.store.get(schedule_id)
        assert (got.enabled, got.last_error) == (False, "owner_disabled"), schedule_id
        assert got.owner_user_id == OWNER
    theirs = rig.store.get("sched_b1")
    assert (theirs.enabled, theirs.last_error, theirs.failures) == (True, None, 0)
    assert theirs.next_due == MON_0330Z


def test_FR_AGT_14_disable_for_owner_is_idempotent_and_an_owner_with_nothing_changes_nothing(rig: StoreRig) -> None:
    _two_owners(rig)
    assert rig.store.disable_for_owner(OWNER) == 2
    assert rig.store.disable_for_owner(OWNER) == 0  # nothing left to change
    assert rig.store.disable_for_owner("u_nobody") == 0
    assert rig.store.get("sched_b1").enabled is True


def test_FR_AGT_14_disable_for_owner_keeps_the_record_and_the_snapshot(rig: StoreRig) -> None:
    rig.add(make_record("sched_a1"))
    before = rig.store.get("sched_a1")
    rig.store.disable_for_owner(OWNER)
    after = rig.store.get("sched_a1")
    for name in ("title", "cadence", "budget_cap", "brief", "approach", "approved_brief_ref", "next_due", "created_at"):
        assert getattr(after, name) == getattr(before, name), name


def test_FR_AGT_14_disable_for_owner_also_disables_a_schedule_that_is_backed_off_or_claimed(rig: StoreRig) -> None:
    rig.add(make_record("sched_a1"))
    assert rig.store.claim("sched_a1", MON_0330Z) is True  # a tick holds it right now
    assert rig.store.disable_for_owner(OWNER) == 1
    assert rig.store.get("sched_a1").enabled is False
    assert rig.store.claim("sched_a1", MON_0330Z) is False  # and nothing can claim it from here on


@pytest.mark.parametrize(
    "bad_owner",
    [
        "",
        "*",
        "u_",
        "owner",
        "u_a b",
        "u_a/b",
        "../x",
        "u_" + "x" * 60,
        f"{OWNER}\n",
        f" {OWNER}",
        f"{OWNER}*",
        None,
        5,
        b"u_owner",
    ],
)
def test_FR_AGT_14_disable_for_owner_refuses_an_invalid_owner_id_and_changes_nothing(
    rig: StoreRig, bad_owner: Any
) -> None:
    """Refused either way the other methods refuse a bad id (a ValueError, or a count of 0): never a match."""
    _two_owners(rig)
    try:
        changed = rig.store.disable_for_owner(bad_owner)
    except ValueError:
        changed = 0
    assert changed == 0
    for schedule_id in ("sched_a1", "sched_a2", "sched_b1"):
        got = rig.store.get(schedule_id)
        assert (got.enabled, got.last_error) == (True, None), schedule_id


def test_FR_AGT_14_a_disabled_owners_schedule_never_fires_in_a_tick() -> None:
    rig = make_tick_rig(
        [
            make_record("sched_a1"),
            make_record("sched_a2", next_due=MON_0330Z - WEEK),
            make_record("sched_b1", owner_user_id=OTHER),
        ]
    )
    assert rig.store.disable_for_owner(OWNER) == 2
    assert rig.ticker.tick().fired == 1
    assert [r.schedule_id for r in rig.starter.started] == ["sched_b1"]
    for _ in range(3):
        rig.clock.advance(timedelta(days=8))
        rig.ticker.tick()
    assert {r.owner_user_id for r in rig.starter.attempts} == {OTHER}  # not one attempt for the disabled owner


def test_FR_AGT_14_a_slot_claimed_before_the_disable_starts_nothing_on_the_next_tick() -> None:
    """A claim held while the owner is disabled is released afterwards: the next tick starts nothing for the owner."""
    rig = make_tick_rig([make_record("sched_a1")])
    assert rig.store.claim("sched_a1", MON_0330Z) is True
    assert rig.store.disable_for_owner(OWNER) == 1
    rig.store.release("sched_a1", MON_0330Z)
    rig.clock.advance(timedelta(minutes=1))
    assert rig.ticker.tick().fired == 0
    assert rig.starter.attempts == []


# --- ScheduleRetention ----------------------------------------------------------------------------------------------


def test_FR_AGT_14_schedule_retention_is_a_retention_store_over_every_schedule_with_its_owner(rig: StoreRig) -> None:
    _two_owners(rig)
    retention = _retention(rig.store)
    assert callable(retention.records) and callable(retention.delete)
    records = list(retention.records())
    assert sorted(r.record_id for r in records) == ["sched_a1", "sched_a2", "sched_b1"]
    by_id = {r.record_id: r for r in records}
    assert (by_id["sched_a1"].user_id, by_id["sched_a2"].user_id, by_id["sched_b1"].user_id) == (OWNER, OWNER, OTHER)
    for record in records:
        assert isinstance(record.entity, str) and record.entity
        assert isinstance(record.created_at, datetime) and record.created_at.tzinfo is not None
    assert len({r.record_id for r in records}) == len(records)  # unique within the store


def test_FR_AGT_14_schedule_retention_records_is_a_fresh_read_every_time(rig: StoreRig) -> None:
    retention = _retention(rig.store)
    assert list(retention.records()) == []
    rig.add(make_record("sched_a1"))
    assert [r.record_id for r in retention.records()] == ["sched_a1"]
    rig.store.delete("sched_a1")
    assert list(retention.records()) == []


def test_FR_AGT_14_schedule_retention_reports_a_disabled_schedule_too(rig: StoreRig) -> None:
    rig.add(make_record("sched_a1", enabled=False))
    assert [(r.record_id, r.user_id) for r in _retention(rig.store).records()] == [("sched_a1", OWNER)]


def test_FR_AGT_14_schedule_retention_delete_removes_the_document_and_is_idempotent(rig: StoreRig) -> None:
    _two_owners(rig)
    retention = _retention(rig.store)
    retention.delete("sched_a1")
    assert rig.store.get("sched_a1") is None and rig.store.read_doc("sched_a1") is None
    retention.delete("sched_a1")  # again: no error
    retention.delete("sched_missing")
    assert rig.store.get("sched_a2") is not None and rig.store.get("sched_b1") is not None
    for odd in ("", "../x", "sched_a/b", "w_world"):
        retention.delete(odd)  # an id that cannot be a schedule is simply not there; never a path, never a raise
    assert sorted(r.record_id for r in retention.records()) == ["sched_a2", "sched_b1"]


def test_FR_AGT_14_erasing_owner_a_removes_only_a_schedules_and_verify_finds_nothing(rig: StoreRig) -> None:
    _two_owners(rig)
    registry = _registry(_retention(rig.store))
    report = erase_user(registry, request_erasure(OWNER, requested_at=NOW), now=NOW)
    assert report.complete is True
    assert report.removed["firestore"] == 2 and report.remaining["firestore"] == 0
    assert report.failures == {}
    assert rig.store.list_for_owner(OWNER) == []
    assert rig.store.read_doc("sched_a1") is None and rig.store.read_doc("sched_a2") is None
    assert [s.schedule_id for s in rig.store.list_for_owner(OTHER)] == ["sched_b1"]
    verdict = verify_erasure(registry, OWNER)
    assert verdict.ok is True and verdict.remaining["firestore"] == 0 and verdict.problems == []
    other = verify_erasure(registry, OTHER)  # the other user is untouched, and verify says so (read-only)
    assert other.ok is False and other.remaining["firestore"] == 1


def test_FR_AGT_14_erasing_an_owner_with_no_schedules_removes_nothing(rig: StoreRig) -> None:
    _two_owners(rig)
    report = erase_user(_registry(_retention(rig.store)), request_erasure("u_nobody", requested_at=NOW), now=NOW)
    assert (report.complete, report.removed["firestore"]) == (True, 0)
    assert sorted(s.schedule_id for s in rig.store.list_for_owner(OWNER)) == ["sched_a1", "sched_a2"]


def test_FR_AGT_14_erasure_also_removes_a_record_that_cannot_be_decoded(rig: StoreRig) -> None:
    """A quarantined or malformed document still holds the owner's data: it is enumerated by its raw owner and removed.
    A document with no owner at all is nobody's and stays (erasure never deletes what it cannot attribute)."""
    rig.add(make_record("sched_a1"))
    rig.store.insert_raw({"schedule_id": "sched_bad", "owner_user_id": OWNER, "enabled": False, "next_due": MON_0330Z})
    rig.store.insert_raw({"schedule_id": "sched_ownerless", "enabled": False, "next_due": MON_0330Z})
    registry = _registry(_retention(rig.store))
    report = erase_user(registry, request_erasure(OWNER, requested_at=NOW), now=NOW)
    assert report.complete is True and report.removed["firestore"] == 2
    assert rig.store.read_doc("sched_bad") is None and rig.store.read_doc("sched_a1") is None
    assert rig.store.read_doc("sched_ownerless") is not None
    assert verify_erasure(registry, OWNER).ok is True


def test_FR_AGT_14_a_failing_delete_is_reported_by_type_name_and_never_reported_as_complete() -> None:
    """A delete that fails is reported by name, never as complete, and the other owner's data is safe."""
    rig = memory_rig()
    _two_owners(rig)
    store = rig.store
    inner = _retention(store)

    class Failing:
        def records(self) -> Any:
            return inner.records()

        def delete(self, record_id: str) -> None:
            if record_id == "sched_a1":
                raise RuntimeError("firestore says: password hunter2")
            inner.delete(record_id)

    report = erase_user(_registry(Failing()), request_erasure(OWNER, requested_at=NOW), now=NOW)
    assert report.complete is False and report.remaining["firestore"] == 1
    assert report.failures == {"firestore": "RuntimeError"}  # the type name only, never the message
    assert store.get("sched_a2") is None and store.get("sched_b1") is not None


def test_FR_AGT_14_after_erasure_a_due_schedule_of_the_erased_owner_cannot_fire() -> None:
    rig = make_tick_rig([make_record("sched_a1"), make_record("sched_b1", owner_user_id=OTHER)])
    erase_user(_registry(_retention(rig.store)), request_erasure(OWNER, requested_at=NOW), now=NOW)
    assert rig.ticker.tick().fired == 1
    assert [r.schedule_id for r in rig.starter.started] == ["sched_b1"]
