"""FR-MEM-09: "Retention and deletion per section 16" (PRD 13.5). This file covers the retention half: the windows of
PRD 15.1 (Entities, "Retention (default)") and the purge that applies them. Section 16.5: "Retention and deletion: as
in section 15.1".

`tilo_memory` does not exist yet, so these fail at import. Fake stores only (API_FR_MEM_03_09.md).
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from _memory_lib import NOW, FakeStore, Rec, ago, build_registry
from hypothesis import given, settings
from hypothesis import strategies as st
from tilo_memory.retention import RETENTION_DAYS, purge_expired, retention_days

settings.register_profile("memory", deadline=None)
settings.load_profile("memory")

# PRD 15.1, entity -> default retention in days (None = life of account / until unbound / until disconnected).
PRD_15_1 = {
    "org": None,
    "user": None,
    "channel_binding": None,
    "connection": None,
    "policy": None,
    "policy_history": 365,  # "Life of account; history 1 year"
    "task": 90,
    "world": 90,
    "run": 90,
    "event_live": 30,  # "Firestore (live, 30 days)"
    "event_ledger": 365,  # "BigQuery (ledger, 1 year)"
    "card": 90,
    "artifact": 90,
    "decision": 365,  # "1 year"
    "archive_record": 30,  # "30 days in demo; configurable"
}


@pytest.mark.parametrize(("entity", "days"), sorted(PRD_15_1.items()))
def test_FR_MEM_09_default_retention_matches_prd_15_1(entity, days):
    assert retention_days(entity) == days


def test_FR_MEM_09_cache_entry_retention_is_between_7_and_30_days():
    """PRD 15.1 CacheEntry: "7-30 days by source"."""
    assert 7 <= retention_days("cache_entry") <= 30


def test_FR_MEM_09_every_prd_entity_is_in_the_table():
    assert set(PRD_15_1) | {"cache_entry"} <= set(RETENTION_DAYS)


def test_FR_MEM_09_unknown_entity_is_an_error_not_forever():
    with pytest.raises(ValueError):
        retention_days("not_an_entity")


def test_FR_MEM_09_purge_removes_records_older_than_their_window_in_every_store():
    store_a, store_b = FakeStore(), FakeStore()
    store_a.add(Rec("task", "t-old", ago(91), "u_a"))
    store_a.add(Rec("task", "t-new", ago(89), "u_a"))
    store_b.add(Rec("event_live", "e-old", ago(31), "u_a"))
    store_b.add(Rec("event_live", "e-new", ago(29), "u_a"))
    store_b.add(Rec("event_ledger", "l-old", ago(366), "u_a"))
    store_b.add(Rec("event_ledger", "l-new", ago(364), "u_a"))
    removed = purge_expired({"firestore": store_a, "bigquery_ledger": store_b}, now=NOW)
    assert store_a.ids() == {"t-new"}
    assert store_b.ids() == {"e-new", "l-new"}
    assert removed == {"firestore": 1, "bigquery_ledger": 2}


def test_FR_MEM_09_a_record_exactly_at_its_window_is_kept_one_second_later_it_is_purged():
    """BQ-196: "30 days" means kept through day 30; expired only when strictly older."""
    store = FakeStore([Rec("archive_record", "at", ago(30), None), Rec("archive_record", "past", ago(30, 1), None)])
    purge_expired({"gcs_archive": store}, now=NOW)
    assert store.ids() == {"at"}


def test_FR_MEM_09_records_with_no_window_are_never_purged():
    store = FakeStore(
        [
            Rec("user", "u", ago(5000), "u_a"),
            Rec("org", "o", ago(5000), None),
            Rec("connection", "c", ago(5000), "u_a"),
            Rec("channel_binding", "b", ago(5000), "u_a"),
            Rec("policy", "p", ago(5000), "u_a"),
        ]
    )
    assert purge_expired({"firestore": store}, now=NOW) == {"firestore": 0}
    assert len(store.ids()) == 5


def test_FR_MEM_09_purge_is_idempotent():
    store = FakeStore([Rec("run", "r-old", ago(200), "u_a"), Rec("run", "r-new", ago(1), "u_a")])
    registry = {"firestore": store}
    assert purge_expired(registry, now=NOW) == {"firestore": 1}
    assert purge_expired(registry, now=NOW) == {"firestore": 0}
    assert store.ids() == {"r-new"}


def test_FR_MEM_09_purge_reports_every_store_even_when_it_removes_nothing():
    registry = build_registry(["firestore", "gcs_archive"])
    assert purge_expired(registry, now=NOW) == {"firestore": 0, "gcs_archive": 0}


@given(
    entity=st.sampled_from(sorted(e for e, d in PRD_15_1.items() if d is not None)),
    age_seconds=st.integers(min_value=0, max_value=int(timedelta(days=800).total_seconds())),
)
def test_FR_MEM_09_property_purge_removes_a_record_exactly_when_it_is_older_than_its_window(entity, age_seconds):
    """Invariant: never early (no record inside its window is lost), never late (nothing older survives)."""
    window = timedelta(days=PRD_15_1[entity])
    age = timedelta(seconds=age_seconds)
    store = FakeStore([Rec(entity, "x", NOW - age, "u_a")])
    purge_expired({"firestore": store}, now=NOW)
    assert (store.ids() == set()) == (age > window)
