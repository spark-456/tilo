"""PPL-11c-FS-1c fix pass (Opus security review of PR #581): a transaction reads first and writes last, an unknown
`AlreadyExists` path is not given a class, and the backoff pre-check does not wait for the build lock.

The SDK raises `ReadAfterWriteError` (client side) for a transactional read once a write is buffered, so a store that
buffers `txn.delete` of the old reservation and then reads the new one works on no real Firestore. The fake client of
`_ppl11c_fs_fake` now refuses the same way, so the non-emulator flows below catch the old order (they fail on it).
"""

from __future__ import annotations

import threading

import pytest
from _ppl11c_fs_fake import FakeFirestore
from _ppl11c_fs_lib import SENTINEL, email_path, person, record_path, unique_org
from fastapi import HTTPException
from google.cloud.firestore_v1 import ReadAfterWriteError
from tilo_api.people_firestore import _collided, firestore_people_stores
from tilo_people import errors


def _stores():
    db = FakeFirestore()
    return unique_org(), db, firestore_people_stores(db).persons


# --- the fake is as strict as the SDK --------


def test_PPL_11c_FS_20_the_fake_refuses_a_transactional_read_after_a_buffered_write():
    db = FakeFirestore()
    txn = db.transaction()
    txn.create(db.document("orgs/org_a/people_person/u_a"), {"version": 1})
    with pytest.raises(ReadAfterWriteError):
        db.document("orgs/org_a/people_person/u_b").get(transaction=txn)
    with pytest.raises(ReadAfterWriteError):
        list(db.collection("orgs/org_a/people_person").limit(1).stream(transaction=txn))
    assert db.document("orgs/org_a/people_person/u_b").get().exists is False, "a plain read is not a transactional one"


# --- every flow reads everything before it writes --------


def test_PPL_11c_FS_20_replace_that_moves_an_address_reads_both_reservations_before_it_writes():
    org, db, persons = _stores()
    persons.create(person("u_nina", org, email="old@example.com"))
    moved = person("u_nina", org, email="new@example.com")
    persons.replace(moved, expected_version=1)
    assert db.raw(email_path(org, "old@example.com")) is None
    assert db.raw(email_path(org, "new@example.com")) == {"person_id": "u_nina"}
    assert persons.get(org, "u_nina").record["email"] == "new@example.com"


def test_PPL_11c_FS_20_create_create_founder_and_delete_read_before_they_write():
    org, db, persons = _stores()
    persons.create_founder(person("u_f", org, role="owner", email="f@example.com"))
    persons.create(person("u_a", org, email="a@example.com"))
    persons.delete(org, "u_a", expected_version=1)
    assert db.raw(email_path(org, "a@example.com")) is None and db.raw(record_path(org, "person", "u_a")) is None
    assert db.raw(email_path(org, "f@example.com")) == {"person_id": "u_f"}


def test_PPL_11c_FS_20_delete_not_last_reads_the_people_before_it_writes_and_refuses_the_sole_person():
    org, db, persons = _stores()
    persons.create(person("u_a", org, email="a@example.com"))
    persons.create(person("u_b", org, email="b@example.com"))
    persons.delete_not_last(org, "u_a", expected_version=1)
    assert db.raw(record_path(org, "person", "u_a")) is None
    with pytest.raises(errors.LastPerson):
        persons.delete_not_last(org, "u_b", expected_version=1)
    assert db.raw(record_path(org, "person", "u_b")) is not None
    assert db.raw(email_path(org, "b@example.com")) == {"person_id": "u_b"}


# --- an unknown AlreadyExists path is not given a class --------


def test_PPL_11c_FS_20_collided_maps_the_known_paths_and_nothing_else():
    base = "Document already exists: projects/p/databases/(default)/documents/orgs/org_a/"
    assert isinstance(_collided(base + "people_directory/founder", "u_a"), errors.OrgAlreadyFounded)
    assert isinstance(_collided(base + "people_directory/email_" + "0" * 64, "u_a"), errors.EmailTaken)
    assert isinstance(_collided(base + "people_person/u_a", "u_a"), errors.AlreadyExists)
    unknown = _collided(base + "something_else/x", "u_a")
    assert type(unknown) is errors.PeopleError, type(unknown).__name__
    assert type(_collided("no path at all", "u_a")) is errors.PeopleError


# --- the backoff pre-check does not wait for the build lock --------


def test_PPL_11c_FS_20_a_request_inside_the_backoff_window_does_not_wait_for_a_hung_build(monkeypatch):
    from tilo_api import deps

    for name in ("TILO_PEOPLE_BOOTSTRAP_UID", "K_SERVICE", "CLOUD_RUN_JOB", "TILO_API_DEV"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TILO_PEOPLE_STORE", "firestore")
    monkeypatch.setenv("TILO_FIRESTORE_PROJECT", "tilo-test-project")
    calls = []

    def failing_client(*args, **kwargs):
        calls.append(1)
        raise RuntimeError(f"cannot reach {SENTINEL}")

    monkeypatch.setattr("google.cloud.firestore.Client", failing_client)
    monkeypatch.setattr(deps, "people_stores_clock", lambda: 1000.0, raising=False)
    deps.get_people_stores.cache_clear()
    try:
        with pytest.raises(HTTPException):
            deps.get_people_stores()  # the failed build opens the window
        assert len(calls) == 1
        outcome: list[BaseException | None] = []

        def request():
            try:
                deps.get_people_stores()
                outcome.append(None)
            except BaseException as exc:
                outcome.append(exc)

        with deps._people_stores_lock:  # another request is inside a hung build
            worker = threading.Thread(target=request)
            worker.start()
            worker.join(timeout=2)
            answered = not worker.is_alive()
        worker.join(timeout=5)
        assert answered, "a request inside the window waited for the build lock"
        assert isinstance(outcome[0], HTTPException) and outcome[0].status_code == 503
        assert outcome[0].detail == "not_configured" and len(calls) == 1
    finally:
        deps.get_people_stores.cache_clear()
