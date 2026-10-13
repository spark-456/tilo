"""FR-MTR-10 / BQ-MTR10-4 (ticket T3): `FirestoreTreasuryLedger`, the Treasury's credit ledger on Firestore, on
`_adr35_l2_fake.OccFirestore` (no network, no credentials): one org-scoped collection `orgs/{org}/treasury_ledger`,
append-only, an entry id counts once (the same id on other terms is refused), bad entries are refused before any
write, and a read that fails, finds a document that is not an entry or finds too many rows raises: never a partial
list. The seams and the routes on it are `test_FR_MTR_10_T3_treasury_ledger_seams.py`."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from _adr35_l2_fake import OccFirestore
from _t3_ledger_lib import AT, OWNER, ROOT, Flaky, entry, make
from tilo_metering.prices import Usage


def test_FR_MTR_10_BQ_MTR10_4_an_entry_id_counts_once_and_the_same_id_on_other_terms_is_refused():
    db = OccFirestore()
    ledger = make(db)
    one = entry(credits=3.0, usage=Usage("lite-31", 1000, 200, 100, 1, 0))
    ledger.append_once("unit_a", one)
    ledger.append_once("unit_a", one)  # a retry: the same entry, nothing added
    assert len(db.docs) == 1 and ledger.entries_for(OWNER) == [one]
    with pytest.raises(ValueError):
        ledger.append_once("unit_a", entry(credits=9.0))
    with pytest.raises(ValueError):
        ledger.append_once("a/b", one)
    ledger.append(one)
    ledger.append(one)  # no id given: each is its own entry
    assert len(db.docs) == 3


def test_FR_MTR_10_BQ_MTR10_4_the_store_is_org_scoped_and_refuses_bad_entries_before_any_write():
    db = OccFirestore()
    ledger = make(db)
    for bad in (
        entry(org="org_other"),
        entry(credits=float("nan")),
        entry(credits=-1.0),
        entry(user=""),
        entry(at=datetime(2026, 10, 13, 9, 30)),
    ):
        with pytest.raises((TypeError, ValueError)):
            ledger.append(bad)
    assert db.docs == {} and db.attempted_ops == []
    ledger.append(entry())
    assert all(p.startswith(ROOT + "/") for p in db.docs)
    from tilo_api.treasury_firestore import FirestoreTreasuryLedger

    assert FirestoreTreasuryLedger(db, org_id="org_other").entries_for(OWNER) == [], "another org's path"


def test_FR_MTR_10_BQ_MTR10_4_a_read_that_fails_or_is_too_large_raises_never_a_partial_list(monkeypatch):
    from tilo_api import treasury_firestore as tf

    db = Flaky()
    ledger = make(db)
    for credits in (3.0, 1.0, 2.0):
        ledger.append(entry(credits=credits, at=AT + timedelta(seconds=credits)))  # oldest first, whatever the order
    assert [e.credits for e in ledger.entries_for(OWNER)] == [1.0, 2.0, 3.0]
    monkeypatch.setattr(tf, "MAX_ENTRIES", 2)
    with pytest.raises(tf.LedgerUnreadable):
        ledger.entries_for(OWNER)
    monkeypatch.undo()
    db.broken = True
    with pytest.raises(ConnectionError):
        ledger.entries_for(OWNER)


def test_FR_MTR_10_BQ_MTR10_4_one_document_that_is_not_an_entry_refuses_the_whole_read():
    from tilo_api.treasury_firestore import LedgerUnreadable

    db = OccFirestore()
    ledger = make(db)
    ledger.append(entry())
    db.put(
        f"{ROOT}/hand_written", {"kind": "commit", "run": "r_x", "user": OWNER, "org": "org_tilo", "credits": "lots"}
    )
    with pytest.raises(LedgerUnreadable):
        ledger.entries_for(OWNER)
