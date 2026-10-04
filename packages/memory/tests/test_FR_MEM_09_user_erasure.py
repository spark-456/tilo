"""FR-MEM-09: "Deleting a user removes their data from every store within 30 days, verified by a script" (PRD 13.5).
Sources: PRD 16.5 ("account deletion removes data from every store within 30 days"), 15.1 (stores), 13.1/13.2 (the
stores: Firestore, BigQuery ledger, Cloud Storage archive / artifacts / cache blobs, Memory Bank preferences), 16.1
and 16.4 (no secret or personal content in logs).

This file covers the deletion half; `test_FR_MEM_09_erasure_verification_script.py` covers the verifying script.
`tilo_memory` does not exist yet, so these fail at import. Fake stores only (API_FR_MEM_03_09.md). This surface
deletes data on a user's say-so: the security-relevant tests are marked "SECURITY".
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest
from _memory_lib import (
    NOW,
    FailingDeleteStore,
    FakeStore,
    LyingStore,
    Rec,
    ago,
    build_registry,
)
from hypothesis import given, settings
from hypothesis import strategies as st
from tilo_memory.erasure import (
    ERASURE_DEADLINE_DAYS,
    REQUIRED_STORES,
    IncompleteRegistry,
    erase_user,
    request_erasure,
)

settings.register_profile("memory", deadline=None)
settings.load_profile("memory")

ALICE, BOB = "u_alice", "u_bob"


def populated_registry(store_cls=FakeStore):
    """Every required store holds two records of Alice, one of Bob and one record owned by nobody (org level)."""
    registry = build_registry(sorted(REQUIRED_STORES), store_cls=store_cls)
    for name, store in registry.items():
        store.add(Rec("run", f"{name}-alice-1", ago(2), ALICE, payload="alice private text"))
        store.add(Rec("task", f"{name}-alice-2", ago(40), ALICE, payload="alice private text"))
        store.add(Rec("run", f"{name}-bob-1", ago(2), BOB, payload="bob private text"))
        store.add(Rec("org", f"{name}-org-1", ago(2), None, payload="org level"))
    return registry


def test_FR_MEM_09_required_stores_cover_every_prd_store_family():
    """PRD 13.1/13.2: Firestore, BigQuery (ledger), Cloud Storage (archive, artifacts, cache), Memory Bank."""
    names = sorted(REQUIRED_STORES)
    for family in ("firestore", "bigquery", "memory_bank"):
        assert any(n.startswith(family) for n in names), f"no required store for {family}"
    assert any(n.startswith(("gcs", "cloud_storage")) for n in names)
    assert len([n for n in names if n.startswith(("gcs", "cloud_storage"))]) >= 3, "archive, artifacts and cache blobs"


def test_FR_MEM_09_request_sets_a_30_day_deadline():
    request = request_erasure(ALICE, requested_at=NOW)
    assert ERASURE_DEADLINE_DAYS == 30
    assert request.user_id == ALICE
    assert request.requested_at == NOW
    assert request.deadline == NOW + timedelta(days=30)


def test_FR_MEM_09_erasing_a_user_removes_their_records_from_every_store():
    registry = populated_registry()
    report = erase_user(registry, request_erasure(ALICE, requested_at=NOW), now=NOW)
    for name, store in registry.items():
        assert not [r for r in store.records() if r.user_id == ALICE], f"{name} still holds Alice's data"
    assert report.complete is True
    assert report.remaining == {name: 0 for name in registry}
    assert report.removed == {name: 2 for name in registry}
    assert report.failures == {}
    assert report.late is False


def test_FR_MEM_09_erasing_a_user_leaves_everyone_elses_data_alone():
    """SECURITY: deleting Alice must not delete Bob's records or records that belong to no user."""
    registry = populated_registry()
    erase_user(registry, request_erasure(ALICE, requested_at=NOW), now=NOW)
    for name, store in registry.items():
        assert store.ids() == {f"{name}-bob-1", f"{name}-org-1"}


def test_FR_MEM_09_erasing_the_same_user_twice_is_safe():
    registry = populated_registry()
    request = request_erasure(ALICE, requested_at=NOW)
    erase_user(registry, request, now=NOW)
    second = erase_user(registry, request, now=NOW)
    assert second.complete is True
    assert second.removed == {name: 0 for name in registry}


@pytest.mark.parametrize("bad_id", ["", "   ", None, 7, "*", "%", "u_*"])
def test_FR_MEM_09_request_for_a_blank_or_wildcard_user_is_refused(bad_id):
    """SECURITY: an empty id must never match the records that have no owner (user_id None), and a wildcard
    must never match everyone. User ids look like `u_<alnum>` (contracts/common.schema.json user_id)."""
    with pytest.raises(ValueError):
        request_erasure(bad_id, requested_at=NOW)


def test_FR_MEM_09_request_needs_a_timezone_aware_time():
    with pytest.raises(ValueError):
        request_erasure(ALICE, requested_at=NOW.replace(tzinfo=None))


def test_FR_MEM_09_blank_user_never_deletes_ownerless_records_even_if_forced():
    """SECURITY: a hand-built request with user_id None must not delete the org-level records."""
    registry = populated_registry()
    corrupted = SimpleNamespace(user_id=None, requested_at=NOW, deadline=NOW + timedelta(days=30))
    with pytest.raises(ValueError):
        erase_user(registry, corrupted, now=NOW)
    for name, store in registry.items():
        assert f"{name}-org-1" in store.ids()
        assert len(store.ids()) == 4


def test_FR_MEM_09_incomplete_registry_is_refused_and_deletes_nothing():
    """A deletion that skips a store would claim a false erasure: fail closed, delete nothing, name the gap."""
    registry = populated_registry()
    missing = sorted(REQUIRED_STORES)[0]
    del registry[missing]
    with pytest.raises(IncompleteRegistry) as excinfo:
        erase_user(registry, request_erasure(ALICE, requested_at=NOW), now=NOW)
    assert missing in str(excinfo.value)
    for store in registry.values():
        assert len(store.ids()) == 4
        assert store.delete_calls == []


def test_FR_MEM_09_extra_stores_in_the_registry_are_erased_too():
    registry = populated_registry()
    registry["extra_new_store"] = FakeStore([Rec("run", "x-1", ago(1), ALICE)])
    report = erase_user(registry, request_erasure(ALICE, requested_at=NOW), now=NOW)
    assert registry["extra_new_store"].ids() == set()
    assert report.complete is True


def test_FR_MEM_09_one_failing_store_does_not_stop_the_others_and_the_report_says_so():
    registry = populated_registry()
    broken = sorted(REQUIRED_STORES)[1]
    registry[broken] = FailingDeleteStore(registry[broken].records())
    report = erase_user(registry, request_erasure(ALICE, requested_at=NOW), now=NOW)
    assert report.complete is False
    assert set(report.failures) == {broken}
    assert report.remaining[broken] == 2
    for name, store in registry.items():
        if name != broken:
            assert not [r for r in store.records() if r.user_id == ALICE]


def test_FR_MEM_09_a_rerun_after_a_failure_completes_the_erasure():
    registry = populated_registry()
    broken = sorted(REQUIRED_STORES)[1]
    healthy = FakeStore(registry[broken].records())
    registry[broken] = FailingDeleteStore(healthy.records())
    request = request_erasure(ALICE, requested_at=NOW)
    assert erase_user(registry, request, now=NOW).complete is False
    registry[broken] = healthy  # the store is back
    assert erase_user(registry, request, now=NOW + timedelta(days=1)).complete is True
    assert not [r for r in healthy.records() if r.user_id == ALICE]


def test_FR_MEM_09_a_store_that_claims_success_but_keeps_data_is_not_complete():
    """Completion is judged by re-reading the store, not by trusting delete() (the verifying script's rule)."""
    registry = populated_registry()
    lying = sorted(REQUIRED_STORES)[2]
    registry[lying] = LyingStore(registry[lying].records())
    report = erase_user(registry, request_erasure(ALICE, requested_at=NOW), now=NOW)
    assert report.complete is False
    assert report.remaining[lying] == 2


def test_FR_MEM_09_erasure_inside_30_days_is_on_time_and_after_30_days_is_late_but_still_done():
    request = request_erasure(ALICE, requested_at=NOW)
    on_time = erase_user(populated_registry(), request, now=NOW + timedelta(days=30))
    assert on_time.late is False and on_time.complete is True
    late_registry = populated_registry()
    late = erase_user(late_registry, request, now=NOW + timedelta(days=30, seconds=1))
    assert late.late is True
    assert late.complete is True  # lateness is reported, never a reason to leave data behind
    assert not [r for s in late_registry.values() for r in s.records() if r.user_id == ALICE]


def test_FR_MEM_09_report_never_contains_the_users_data():
    """SECURITY (PRD 16.1, 16.4): reports and errors carry store names and counts, never record content."""
    registry = populated_registry()
    broken = sorted(REQUIRED_STORES)[0]
    registry[broken] = FailingDeleteStore(registry[broken].records())
    report = erase_user(registry, request_erasure(ALICE, requested_at=NOW), now=NOW)
    text = repr(report) + repr(report.failures)
    assert "alice private text" not in text
    assert "bob private text" not in text


@given(
    owners=st.lists(st.sampled_from([ALICE, BOB, "u_carol", None]), min_size=0, max_size=12),
    ages=st.lists(st.integers(min_value=0, max_value=800), min_size=12, max_size=12),
)
def test_FR_MEM_09_property_after_erasure_the_user_has_nothing_and_nobody_else_lost_anything(owners, ages):
    """Invariant over any mix of owners, ages and stores: zero of the user's records remain; the multiset of
    other owners' records is unchanged."""
    registry = build_registry(sorted(REQUIRED_STORES))
    for i, name in enumerate(sorted(REQUIRED_STORES)):
        for j, owner in enumerate(owners):
            registry[name].add(Rec("run", f"{name}-{j}", ago(ages[j]), owner))
    before = {n: {r.record_id for r in s.records() if r.user_id != ALICE} for n, s in registry.items()}
    report = erase_user(registry, request_erasure(ALICE, requested_at=NOW), now=NOW)
    assert report.complete is True
    for name, store in registry.items():
        assert not [r for r in store.records() if r.user_id == ALICE]
        assert store.ids() == before[name]
