"""FR-MTG-08 durable DraftStore: offline first-writer wins, tenant isolation and closed door."""

from __future__ import annotations

import copy
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from _ppl11c_fs_fake import FakeFirestore
from fastapi import HTTPException
from google.api_core import exceptions as gexc

USER, OTHER, ORG = "u_" + "a" * 48, "u_" + "b" * 48, "org_tilo"
SECRET = "private minutes and recipients must never reach logs"
VALUE = {
    "status": "ready",
    "draft": {"body": SECRET, "to": ["owner@example.invalid"], "attachments": [], "version": 1},
    "findings": [{"kind": "review", "data": {"safe": True, "missing": None}}],
    "questions": [],
    "nested": [["meeting"], [1, None, True]],
    "flagged": False,
    "drafted_at": 123.5,
}


class LockedFirestore(FakeFirestore):
    """Firestore create's atomic precondition under competing callers, with injected IO failure."""

    def __init__(self):
        super().__init__()
        self.lock = threading.Lock()
        self.failure = None

    def commit(self, ops):
        with self.lock:
            if self.failure is not None:
                raise self.failure
            super().commit(ops)

    def read(self, path):
        with self.lock:
            if self.failure is not None:
                raise self.failure
            return super().read(path)


def store(db, org=ORG):
    from tilo_api.draft_firestore import FirestoreDraftStore

    return FirestoreDraftStore(db, org_id=org)


def assert_closed(call, detail="store_unavailable"):
    with pytest.raises(HTTPException) as caught:
        call()
    assert caught.value.status_code == 503
    assert caught.value.detail == detail
    assert caught.value.headers.get("Cache-Control") == "no-store"


def test_FR_MTG_08_durable_roundtrip_no_overwrite_and_no_aliasing():
    db = LockedFirestore()
    first, restarted = store(db), store(db)
    assert first.get(USER, "mt_a:follow-up") is None
    payload = copy.deepcopy(VALUE)
    assert first.create(USER, "mt_a:follow-up", payload) is True
    payload["draft"]["body"] = "changed caller object"
    assert restarted.get(USER, "mt_a:follow-up") == VALUE
    assert restarted.create(USER, "mt_a:follow-up", {"status": "failed"}) is False
    received = restarted.get(USER, "mt_a:follow-up")
    received["draft"]["to"].clear()
    assert first.get(USER, "mt_a:follow-up") == VALUE
    assert {kind for kind, _ in db.attempted_ops} == {"create"}
    assert len(db.docs) == 1


def test_FR_MTG_08_atomic_contention_across_service_instances():
    db, barrier = LockedFirestore(), threading.Barrier(12)
    stores = [store(db) for _ in range(12)]

    def attempt(i):
        barrier.wait(timeout=5)
        return stores[i].create(USER, "same-instruction", {"winner": i})

    with ThreadPoolExecutor(max_workers=12) as pool:
        answers = list(pool.map(attempt, range(12)))
    assert sum(answers) == 1
    assert store(db).get(USER, "same-instruction") == {"winner": answers.index(True)}
    assert len(db.docs) == 1
    assert {kind for kind, _ in db.attempted_ops} == {"create"}


def test_FR_MTG_08_owner_and_organization_isolation():
    db = LockedFirestore()
    a, b = store(db), store(db, "org_other")
    assert a.create(USER, "same", {"owner": "a"})
    assert a.get(OTHER, "same") is None and b.get(USER, "same") is None
    assert a.create(OTHER, "same", {"owner": "b"})
    assert b.create(USER, "same", {"owner": "c"})
    assert a.get(USER, "same") == {"owner": "a"}
    assert a.get(OTHER, "same") == {"owner": "b"}
    assert b.get(USER, "same") == {"owner": "c"}
    assert len(db.docs) == 3
    assert all(p.startswith(("orgs/org_tilo/", "orgs/org_other/")) for p in db.docs)


def test_FR_MTG_08_instruction_keys_cannot_escape_or_collide_with_emit_markers():
    db = LockedFirestore()
    draft_store = store(db)
    ids = ["mt_a:person/u_a", "../foreign", "a/b", "a%2Fb", "a_b", "#emitted", "é", "é", "x#emit0", "x" * 2000]
    for i, key in enumerate(ids):
        assert draft_store.create(USER, key, {"i": i})
    for i, key in enumerate(ids):
        assert store(db).get(USER, key) == {"i": i}
    paths = list(db.docs)
    assert len(paths) == len(ids)
    assert all(len(p.split("/")) == 4 and p.startswith(f"orgs/{ORG}/") for p in paths)


@pytest.mark.parametrize("method", ["get", "create"])
@pytest.mark.parametrize("error", [gexc.ServiceUnavailable, gexc.PermissionDenied, gexc.Aborted, gexc.Conflict])
def test_FR_MTG_08_non_duplicate_io_failures_are_sanitized_503(method, error, caplog):
    db = LockedFirestore()
    draft_store = store(db)
    db.failure = error(SECRET)
    args = (USER, "private-instruction") + ((VALUE,) if method == "create" else ())
    assert_closed(lambda: getattr(draft_store, method)(*args))
    assert not db.docs
    assert SECRET not in caplog.text and "private-instruction" not in caplog.text


def test_FR_MTG_08_missing_config_never_falls_back_to_memory(monkeypatch):
    from tilo_api import deps, store_door

    def refused(*args, **kwargs):
        raise store_door.ApiStoreNotConfigured(SECRET)

    monkeypatch.setattr(store_door, "open_api_store", refused)
    assert_closed(lambda: deps.get_followup_draft_store(), "not_configured")


def test_FR_MTG_08_existing_door_and_owner_caller_forwarding(monkeypatch):
    from tilo_api import deps, owner_followup_caller, store_door

    db, calls = LockedFirestore(), []

    def opened(*args, **kwargs):
        calls.append((args, kwargs))
        return store_door.FirestoreApiStore("demo-drafts", db)

    monkeypatch.setattr(store_door, "open_api_store", opened)
    first = deps.get_followup_draft_store()
    assert first.create(USER, "persist", VALUE)
    assert deps.get_followup_draft_store().get(USER, "persist") == VALUE
    assert len(calls) == 2
    sentinel = object()
    monkeypatch.setattr(deps, "get_followup_draft_store", lambda: sentinel)
    assert owner_followup_caller.get_owner_followup_drafts() is sentinel
