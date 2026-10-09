"""PROD-WIRE slice 5a (unit): `tilo_api.prod.FirestoreLedger`, the Treasury's ledger kept in Firestore at
`orgs/{org}/ledger/{entry_id}` (FR-MTR-10 reads it, COST-FAST-1b writes it; ADR-0026, ADR-0018 T4: one org). The
emulator half is `test_PROD_WIRE_5a_firestore_ledger_emulator.py`. Helpers and the pinned client calls: `_pw5_lib.py`.

The fake client has Firestore's own write rule for `create` (`AlreadyExists` when the document exists), refuses `set`,
`update`, `delete`, transactions, batches and collection-group reads, and stores a JSON round trip of every body.

Ambiguities resolved (each is the brief's stated rule, none is a new requirement):
- A stored document that does not decode is skipped, never repaired. What counts as not decoding: a missing required
  field (`kind`, `run`, `user`, `org`, `at`), `at` that is not an ISO string with an offset (a naive time would need an
  invented zone), `credits` that is not a number or null, `usage` that is not a `Usage` dict, `day` that is not an
  ISO date.
- Which library exceptions are covered: the brief's `GoogleAPICallError`, `RetryError` and `google.auth` errors; a
  retry on `Aborted` is not pinned here (the emulator test pins the outcome of eight racing appends).
- Cases that differ only by an input value are looped inside one test (each failure names its case).
"""

from __future__ import annotations

import logging
import re
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest
from _pw3_lib import threads
from _pw5_lib import (
    AT,
    SENTINEL,
    LedgerClient,
    doc_path,
    firestore_ledger,
    import_attr,
    make_entry,
    stored_body,
)
from google.api_core import exceptions as gexc
from google.auth import exceptions as gauth_exc
from hypothesis import given, settings
from hypothesis import strategies as st
from tilo_metering import LedgerEntry
from tilo_metering.prices import Usage

ID = "01JB5VQ0000000000000000001"


def _ledger(client=None, **kwargs):
    client = client if client is not None else LedgerClient()
    return firestore_ledger()(client, **kwargs), client


def _prod(name):
    return import_attr("tilo_api.prod", name)


def test_PROD_WIRE_5a_FR_MTR_10_an_entry_is_one_json_safe_document_at_orgs_org_ledger_id():
    ledger, client = _ledger()
    entry = make_entry()
    assert ledger.append(entry, entry_id=ID) is None
    assert list(client.docs) == [doc_path(ID)], "one document, at orgs/org_tilo/ledger/{entry_id}"
    doc = client.docs[doc_path(ID)]  # the fake's create already refused a non-JSON-safe body
    assert (doc["kind"], doc["run"], doc["user"], doc["org"], doc["step"], doc["credits"]) == (
        "commit", "r_pw5_1", "u_pw5_owner", "org_tilo", "U1", 12.5,
    )  # fmt: skip
    assert isinstance(doc["at"], str) and datetime.fromisoformat(doc["at"]) == AT, "datetime as an ISO string"
    assert doc["day"] == "2026-06-01", "date as an ISO string"
    assert doc["usage"] == {"profile": "flash-38", "tokens_in": 1000, "tokens_out": 500}, "Usage as a dict"
    assert (doc["price_effective_date"], doc["price_source"]) == ("2026-06-01", "Fake price sheet for tests.")
    assert client.writes() == []


def test_PROD_WIRE_5a_ADR_0018_one_org_the_default_is_org_tilo_and_another_orgs_path_is_never_read():
    other, client = _ledger(org_id="org_other")
    other.append(make_entry(run="r_theirs", credits=999.0), entry_id="01JB5VQ0000000000000000002")
    assert list(client.docs) == [doc_path("01JB5VQ0000000000000000002", "org_other")], "the org is part of the path"
    mine = firestore_ledger()(client)  # the default org
    assert list(mine.entries()) == [], "org_tilo reads nothing of org_other's"
    good = make_entry(run="r_mine")
    mine.append(good, entry_id=ID)
    client.docs["orgs/org_tilo2/ledger/x"] = dict(client.docs[doc_path(ID)], run="r_lookalike")
    client.docs["ledger/stray"] = dict(client.docs[doc_path(ID)], run="r_stray")
    assert list(mine.entries()) == [good]
    assert [e.run for e in other.entries()] == ["r_theirs"]
    assert all(op[0] != "collection_group" for op in client.ops), "no collection-group read across orgs"


def test_PROD_WIRE_5a_an_identical_append_is_a_no_op_and_another_body_is_a_ledger_conflict_that_changes_nothing():
    ledger, client = _ledger()
    entry = make_entry()
    ledger.append(entry, entry_id=ID)
    before = {path: dict(doc) for path, doc in client.docs.items()}
    assert ledger.append(entry, entry_id=ID) is None
    assert ledger.append(replace(entry), entry_id=ID) is None, "an equal entry, not the same object"
    assert firestore_ledger()(client).append(entry, entry_id=ID) is None, "another process, the same answer"
    assert client.docs == before
    changes = {
        "credits": {"credits": 12.6}, "run": {"run": "r_pw5_other"}, "user": {"user": "u_pw5_other"},
        "at": {"at": AT + timedelta(seconds=1)}, "tokens": {"usage": Usage("flash-38", 1000, 501)},
        "usage-none": {"usage": None}, "kind": {"kind": "reserve"}, "day": {"day": date(2026, 6, 2)},
        "step": {"step": "U2"},
    }  # fmt: skip
    for name, change in changes.items():
        with pytest.raises(_prod("LedgerConflict")):
            ledger.append(make_entry(**change), entry_id=ID)
        assert client.docs == before, f"{name}: the first body stands"


def test_PROD_WIRE_5a_append_is_create_only_never_set_update_delete_a_transaction_or_a_batch():
    ledger, client = _ledger()
    entry = make_entry()
    ledger.append(entry, entry_id=ID)
    ledger.append(entry, entry_id=ID)
    with pytest.raises(_prod("LedgerConflict")):
        ledger.append(make_entry(credits=1.0), entry_id=ID)
    ledger.append_entry(entry)
    ledger.entries()
    assert client.writes() == [], f"append-only: {client.writes()}"
    assert [op for op, _ in client.ops if op == "create"] == ["create"] * 4, "one create per append, nothing else"


def test_PROD_WIRE_5a_an_entry_id_must_be_one_to_128_letters_digits_underscore_or_hyphen():
    bad = ["", "a/b", "/", "a.b", "a b", " a", "a\n", "é", "a" * 129, "orgs/org_tilo/ledger/x", "..", "a:b"]
    for entry_id in bad:
        ledger, client = _ledger()
        calls = len(client.ops)  # building the ledger may touch the client; a refused append must not
        with pytest.raises(ValueError):
            ledger.append(make_entry(), entry_id=entry_id)
        assert len(client.ops) == calls and client.docs == {}, f"{entry_id!r}: ValueError before any client call"
    for entry_id in ["a", "A-z_0-9", ID, "a" * 128, "-", "_"]:
        ledger, client = _ledger()
        ledger.append(make_entry(), entry_id=entry_id)
        assert list(client.docs) == [doc_path(entry_id)], entry_id


def test_PROD_WIRE_5a_FR_MTR_10_entries_round_trips_every_field_exactly_sorted_by_at_then_entry_id():
    ledger, _ = _ledger()
    assert list(ledger.entries()) == [], "an empty ledger is empty, not an error"
    a, b, c, d = (
        make_entry(run=f"r_{n}", at=AT + timedelta(minutes=m)) for n, m in (("a", 2), ("b", 1), ("c", 1), ("d", 0))
    )
    bare = LedgerEntry("release", "r_pw5_2", "u_pw5_owner", "org_tilo", AT - timedelta(days=1))  # no usage, step, day
    for entry, entry_id in ((a, "z1"), (c, "id_2"), (b, "id_1"), (d, "zz"), (bare, "release_1")):  # not in sort order
        ledger.append(entry, entry_id=entry_id)
    got = list(ledger.entries())
    assert got == [bare, d, b, c, a], "by (at, entry_id): b before c at the same instant, since id_1 < id_2"
    assert all(isinstance(e, LedgerEntry) for e in got)
    assert got[1].usage == Usage("flash-38", 1000, 500) and got[1].day == date(2026, 6, 1)
    assert got[1].at.tzinfo is not None and got[1].at == AT and isinstance(got[1].credits, float)


UNDECODABLE = {
    "at-missing": {"drop": "at"},
    "at-not-a-date": {"at": f"{SENTINEL}-not-a-date"},
    "at-naive": {"at": "2026-06-01T12:00:00"},
    "at-a-number": {"at": 1780315200},
    "kind-missing": {"drop": "kind"},
    "kind-a-number": {"kind": 7},
    "run-missing": {"drop": "run"},
    "user-missing": {"drop": "user"},
    "credits-a-string": {"credits": f"{SENTINEL}-12.5"},
    "credits-an-object": {"credits": {"x": 1}},
    "usage-a-string": {"usage": f"{SENTINEL}-flash"},
    "usage-missing-tokens": {"usage": {"profile": "flash-38"}},
    "usage-negative-tokens": {"usage": {"profile": "flash-38", "tokens_in": -1, "tokens_out": 5}},
    "usage-string-tokens": {"usage": {"profile": "flash-38", "tokens_in": SENTINEL, "tokens_out": 5}},
    "day-not-a-date": {"day": f"{SENTINEL}-no-day"},
    "day-a-number": {"day": 20260601},
}


def test_PROD_WIRE_5a_a_stored_document_that_does_not_decode_is_skipped_and_logged_by_type_only(caplog):
    good = make_entry(run="r_good")
    for name, change in UNDECODABLE.items():
        ledger, client = _ledger()
        ledger.append(good, entry_id="good_1")
        body = dict(stored_body(make_entry(run="r_bad")))
        change = dict(change)
        if dropped := change.pop("drop", None):
            body.pop(dropped, None)
        body.update(change)
        client.docs[doc_path("bad_1")] = body
        caplog.clear()
        with caplog.at_level(logging.DEBUG):
            got = list(ledger.entries())  # never raises, never invents a value
        assert got == [good], f"{name}: only the document that decodes"
        assert SENTINEL not in caplog.text, f"{name}: a bad value is never logged"
        assert caplog.records, f"{name}: the skip is logged"


def test_PROD_WIRE_5a_COST_FAST_1b_append_entry_derives_a_deterministic_id_so_a_retry_is_idempotent():
    ledger, client = _ledger()
    entry = make_entry()
    assert ledger.append_entry(entry) is None
    assert ledger.append_entry(replace(entry)) is None, "the same entry again: the same document"
    assert firestore_ledger()(client).append_entry(entry) is None, "another instance: the same document"
    [entry_id] = client.ledger_docs()
    assert re.fullmatch(r"[A-Za-z0-9_-]{1,128}", entry_id), entry_id
    assert list(ledger.entries()) == [entry] and client.writes() == []
    changes = {
        "credits": {"credits": 12.6}, "step": {"step": "U2"}, "at": {"at": AT + timedelta(microseconds=1)},
        "run": {"run": "r_pw5_2"}, "usage": {"usage": None},
    }  # fmt: skip
    for name, change in changes.items():
        ledger.append_entry(make_entry(**change))
        assert len(client.ledger_docs()) == 1 + list(changes).index(name) + 1, (
            f"{name}: a different entry, a new document"
        )
    assert len(ledger.entries()) == 1 + len(changes), "two equal Quick charges a moment apart are two entries"


LIBRARY_ERRORS = {
    "unavailable": lambda: gexc.ServiceUnavailable(SENTINEL),
    "deadline": lambda: gexc.DeadlineExceeded(SENTINEL),
    "permission": lambda: gexc.PermissionDenied(SENTINEL),
    "retry": lambda: gexc.RetryError(SENTINEL, cause=None),
    "transport": lambda: gauth_exc.TransportError(SENTINEL),
    "no-credentials": lambda: gauth_exc.DefaultCredentialsError(SENTINEL),
    "refresh": lambda: gauth_exc.RefreshError(SENTINEL),
}


def test_PROD_WIRE_5a_a_library_error_on_a_write_is_firestore_unavailable_logged_by_type_only(caplog):
    unavailable = _prod("FirestoreUnavailable")
    assert issubclass(unavailable, import_attr("tilo_api.store_door", "ApiStoreUnavailable")), "a 503 store_unavailable"
    for name, make_error in LIBRARY_ERRORS.items():
        for op in ("append", "append_entry", "read-back"):
            ledger, client = _ledger()
            if op == "read-back":  # the document exists, and the read that compares it fails
                ledger.append(make_entry(), entry_id=ID)
                client.fail("get", make_error)
            else:
                client.fail("create", make_error)
            caplog.clear()
            with caplog.at_level(logging.DEBUG), pytest.raises(unavailable) as refused:
                if op == "append_entry":
                    ledger.append_entry(make_entry())
                else:
                    ledger.append(make_entry(), entry_id=ID)
            where = f"{name}/{op}"
            assert SENTINEL not in caplog.text, where
            assert SENTINEL not in str(refused.value) and SENTINEL not in repr(refused.value), where
            assert type(make_error()).__name__ in caplog.text, f"{where}: the type is logged"
            assert (refused.value.status_code, refused.value.detail) == (503, "store_unavailable"), where


def test_PROD_WIRE_5a_a_library_error_on_entries_is_firestore_unavailable_logged_by_type_only(caplog):
    for name, make_error in LIBRARY_ERRORS.items():
        ledger, client = _ledger()
        ledger.append(make_entry(), entry_id=ID)
        client.fail("stream", make_error)
        caplog.clear()
        with caplog.at_level(logging.DEBUG), pytest.raises(_prod("FirestoreUnavailable")) as refused:
            ledger.entries()
        assert SENTINEL not in caplog.text and SENTINEL not in str(refused.value), name
        assert type(make_error()).__name__ in caplog.text, name


def test_PROD_WIRE_5a_eight_concurrent_appends_of_one_id_and_one_body_leave_one_document_and_no_error():
    client = LedgerClient(read_delay=0.01)  # a read-then-write ledger would race here
    ledgers = [firestore_ledger()(client) for _ in range(8)]
    entry = make_entry()
    results = threads(8, lambda i: ledgers[i].append(entry, entry_id=ID))
    assert results == [None] * 8, results
    assert list(client.ledger_docs()) == [ID]
    assert client.writes() == []


def test_PROD_WIRE_5a_eight_concurrent_appends_of_one_id_and_different_bodies_leave_exactly_one_winner():
    client = LedgerClient(read_delay=0.01)
    ledgers = [firestore_ledger()(client) for _ in range(8)]
    entries = [make_entry(credits=float(i + 1)) for i in range(8)]
    results = threads(8, lambda i: ledgers[i].append(entries[i], entry_id=ID))
    assert sum(r is None for r in results) == 1, results
    assert all(isinstance(r, _prod("LedgerConflict")) for r in results if r is not None), results
    [stored] = ledgers[0].entries()
    assert stored in entries


# -- property: any entry round trips, idempotently, in order ----------------------------------------

_ids = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789_", min_size=1, max_size=12)
_entries = st.builds(
    LedgerEntry,
    kind=st.sampled_from(["reserve", "commit", "release", "grant", "usage"]),
    run=_ids.map("r_{}".format),
    user=_ids.map("u_{}".format),
    org=st.just("org_tilo"),
    at=st.datetimes(min_value=datetime(2020, 1, 1), max_value=datetime(2035, 1, 1), timezones=st.just(UTC)),
    step=st.none() | _ids,
    credits=st.none() | st.floats(min_value=0, max_value=1e9, allow_nan=False, allow_infinity=False),
    usage=st.none()
    | st.builds(Usage, st.sampled_from(["flash-38", "lite-31"]), st.integers(0, 10**6), st.integers(0, 10**6)),
    price_effective_date=st.none() | st.just("2026-06-01"),
    price_source=st.none() | _ids,
    day=st.none() | st.dates(min_value=date(2020, 1, 1), max_value=date(2035, 1, 1)),
)


@settings(max_examples=60, deadline=None)
@given(st.lists(_entries, max_size=8))
def test_PROD_WIRE_5a_property_every_entry_round_trips_exactly_a_retry_adds_nothing_and_entries_stay_sorted(entries):
    ledger, client = _ledger()
    for entry in entries:
        ledger.append_entry(entry)
    for entry in entries:  # every retry
        ledger.append_entry(entry)
    got = list(ledger.entries())
    assert sorted(got, key=repr) == sorted(set(entries), key=repr), "exactly the distinct entries, none changed"
    assert [e.at for e in got] == sorted(e.at for e in got), "sorted by at"
    assert client.writes() == []
