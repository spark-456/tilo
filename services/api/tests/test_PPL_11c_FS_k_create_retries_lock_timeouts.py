"""PPL-11c-FS (cloud lane trial on #572, 4 of 60 racing creates): the single-document `create` of a record store
retries the emulator's `Aborted: 409 Transaction lock timeout`, boundedly and with an injectable pause, and a create
whose answer was lost (it landed, the reply did not) is not reported as `AlreadyExists` when the stored document is the
one being created. `replace` and `delete` already retry contention (`_CONTENDED`); `AlreadyExists`, `NotFound` and
`VersionConflict` are never taken for contention. No emulator: a scripted stand-in for the client.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest
from _ppl11c_fs_lib import SENTINEL, make, unique_org
from google.api_core import exceptions as gexc
from tilo_api import people_firestore
from tilo_api.people_firestore import FirestoreRecordStore
from tilo_people import errors


class Ref:
    def __init__(self, db: Stub, path: str) -> None:
        self.db, self.path = db, path

    def create(self, data: dict[str, Any]) -> None:
        self.db.creates += 1
        step = self.db.script.pop(0) if self.db.script else "ok"
        if step == "ok":
            self.db.docs[self.path] = copy.deepcopy(data)
        elif step == "lost_ack":  # it committed, the reply did not arrive
            self.db.docs[self.path] = copy.deepcopy(data)
            raise gexc.Aborted(f"409 Transaction lock timeout {SENTINEL}")
        elif step == "aborted":
            raise gexc.Aborted(f"409 Transaction lock timeout {SENTINEL}")
        elif step == "conflict":
            raise gexc.Conflict(f"409 conflict {SENTINEL}")
        elif step == "exists":
            raise gexc.AlreadyExists(f"Document already exists {SENTINEL}")
        elif step == "denied":
            raise gexc.PermissionDenied(f"denied {SENTINEL}")

    def get(self, **_: Any) -> Any:
        found = self.db.docs.get(self.path)
        return type("Snap", (), {"exists": found is not None, "to_dict": lambda _s: copy.deepcopy(found)})()


class Stub:
    """`script` is consumed one step per `create` call; after it, creates succeed."""

    def __init__(self, *script: str) -> None:
        self.script, self.docs, self.creates = list(script), {}, 0

    def document(self, path: str) -> Ref:
        return Ref(self, path)


@pytest.fixture
def pauses(monkeypatch):
    """The retry pause is injected: a recording stand-in, so no test sleeps."""
    seen: list[int] = []
    monkeypatch.setattr(people_firestore, "_pause", seen.append)
    return seen


def _store(*script: str):
    db = Stub(*script)
    return db, FirestoreRecordStore(db, "work_item")


def test_PPL_11c_FS_21_a_create_that_is_aborted_once_or_twice_is_retried_and_returns_the_record(pauses):
    for aborts in (1, 2):
        db, store = _store(*(["aborted"] * aborts))
        record = make("work_item", 1, unique_org())
        stored = store.create(record)
        assert stored.version == 1 and dict(stored.record) == record
        assert db.creates == aborts + 1 and len(db.docs) == 1


def test_PPL_11c_FS_21_a_create_that_always_aborts_gives_up_with_a_plain_error_with_no_text(pauses):
    db, store = _store(*(["aborted"] * 50))
    with pytest.raises(errors.PeopleError) as caught:
        store.create(make("work_item", 1, unique_org()))
    assert type(caught.value) is errors.PeopleError
    assert db.creates == people_firestore._ATTEMPTS, "bounded: the same attempt count as the other calls"
    assert len(pauses) == people_firestore._ATTEMPTS and db.docs == {}


def test_PPL_11c_FS_21_the_error_text_of_the_library_is_not_echoed(pauses):
    _, store = _store(*(["aborted"] * 50))
    with pytest.raises(errors.PeopleError) as caught:
        store.create(make("work_item", 1, unique_org()))
    assert SENTINEL not in str(caught.value) and SENTINEL not in repr(caught.value)
    assert SENTINEL not in " ".join(map(str, caught.value.args))


def test_PPL_11c_FS_21_a_create_whose_answer_was_lost_is_not_reported_as_already_exists(pauses):
    """Attempt 1 landed but timed out; attempt 2 meets our own document, which equals the record: success."""
    db, store = _store("lost_ack", "exists")
    record = make("work_item", 1, unique_org())
    stored = store.create(record)
    assert stored.version == 1 and dict(stored.record) == record and db.creates == 2


def test_PPL_11c_FS_21_a_retried_create_that_meets_a_different_document_is_already_exists(pauses):
    db, store = _store("aborted", "exists")
    org = unique_org()
    record = make("work_item", 1, org)
    other = copy.deepcopy(record)
    other["title"] = "a different document with the same id"
    db.docs[f"orgs/{org}/people_work_item/{record['id']}"] = {"version": 1, "record": other}
    with pytest.raises(errors.AlreadyExists):
        store.create(record)


def test_PPL_11c_FS_21_guard_an_already_exists_on_the_first_try_is_never_retried_or_swallowed(pauses):
    org = unique_org()
    record = make("work_item", 1, org)
    db, store = _store("exists")
    db.docs[f"orgs/{org}/people_work_item/{record['id']}"] = {"version": 1, "record": record}  # even the same record
    with pytest.raises(errors.AlreadyExists):
        store.create(record)
    assert db.creates == 1 and pauses == []


def test_PPL_11c_FS_21_a_plain_conflict_is_retried_but_other_errors_are_not(pauses):
    db, store = _store("conflict")
    store.create(make("work_item", 1, unique_org()))
    assert db.creates == 2
    db, store = _store("denied")
    with pytest.raises(errors.PeopleError) as caught:
        store.create(make("work_item", 1, unique_org()))
    assert db.creates == 1 and SENTINEL not in str(caught.value)
