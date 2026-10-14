"""FR-MTG-08 scoped durable Autopilot state, fake SDK only."""

from __future__ import annotations

import copy
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from _ppl11c_fs_fake import FakeFirestore
from fastapi import HTTPException
from google.api_core import exceptions as gexc

USER, OTHER = "u_owner", "u_other"
SECRET = "private subject recipient@example.invalid"
VALUE = {"body": SECRET, "nested": [[1, None, True]], "flag": False}


class DB(FakeFirestore):
    def __init__(self):
        super().__init__()
        self.failure = None
        self.lock = threading.Lock()

    def commit(self, ops):
        with self.lock:
            if self.failure:
                raise self.failure
            return super().commit(ops)

    def read(self, path):
        if self.failure:
            raise self.failure
        return super().read(path)


def stores(db, **overrides):
    from tilo_api.followup_autopilot_state import FirestoreCards, FirestoreStops

    scope = dict(org_id="org_tilo", owner=USER, world_id="w_a", run_id="r_a") | overrides
    return FirestoreCards(db, **scope), FirestoreStops(db, **scope)


def closed(call):
    with pytest.raises(HTTPException) as caught:
        call()
    assert caught.value.status_code == 503
    assert caught.value.detail == "store_unavailable"
    assert caught.value.headers.get("Cache-Control") == "no-store"
    assert SECRET not in str(caught.value)


def test_roundtrip_restart_copies_and_update_without_resurrection():
    db = DB()
    cards, _ = stores(db)
    assert cards.get(USER, "card") is None
    value = copy.deepcopy(VALUE)
    assert cards.create(USER, "card", value)
    value["nested"][0].clear()
    restarted, _ = stores(db)
    assert restarted.get(USER, "card") == VALUE
    read = restarted.get(USER, "card")
    read["nested"].clear()
    assert cards.get(USER, "card") == VALUE
    cards.put(USER, "card", {"updated": True})
    assert restarted.get(USER, "card") == {"updated": True}
    closed(lambda: cards.put(USER, "absent", VALUE))
    assert cards.get(USER, "absent") is None
    assert {kind for kind, _ in db.attempted_ops} == {"create", "update"}


def test_atomic_first_writer_and_duplicate_keeps_original():
    db, barrier = DB(), threading.Barrier(8)

    def attempt(i):
        cards, _ = stores(db)
        barrier.wait(timeout=5)
        return cards.create(USER, "same", {"winner": i})

    with ThreadPoolExecutor(max_workers=8) as pool:
        answers = list(pool.map(attempt, range(8)))
    assert sum(answers) == 1
    cards, _ = stores(db)
    assert cards.get(USER, "same") == {"winner": answers.index(True)}
    assert {kind for kind, _ in db.attempted_ops} == {"create"}


def test_scope_isolation_hashed_injection_keys_and_pending_remove():
    db = DB()
    scopes = [{}, {"owner": OTHER}, {"world_id": "w_b"}, {"run_id": "r_b"}, {"org_id": "org_other"}]
    keys = ["../foreign", "a/b", "a%2Fb", "a_b", "#stop", "é", "é", "x" * 2000]
    for scope in scopes:
        cards, stops = stores(db, **scope)
        owner = scope.get("owner", USER)
        for key in keys:
            assert cards.create(owner, key, VALUE)
            stops.add(owner, key)
            stops.add(owner, key)
        assert set(stops.pending()) == {(owner, key) for key in keys}
    assert len(db.docs) == len(scopes) * len(keys) * 2
    for path in db.docs:
        parts = path.split("/")
        assert len(parts) == 6 and parts[0] == "orgs" and parts[2] == "followup_autopilot"
        assert parts[4] in {"cards", "stops"}
        assert len(parts[3]) == len(parts[5]) == 64
        assert all(c in "0123456789abcdef" for c in parts[3] + parts[5])
    _, stops = stores(db)
    stops.remove(USER, keys[0])
    assert (USER, keys[0]) not in stops.pending()
    assert len(stores(db, owner=OTHER)[1].pending()) == len(keys)


def test_cross_owner_refused_and_artifact_index_bound_to_owner():
    db = DB()
    cards, stops = stores(db)
    for call in [
        lambda: cards.get(OTHER, "k"),
        lambda: cards.create(OTHER, "k", VALUE),
        lambda: cards.put(OTHER, "k", VALUE),
        lambda: stops.add(OTHER, "k"),
        lambda: stops.remove(OTHER, "k"),
    ]:
        with pytest.raises(PermissionError):
            call()
    assert not db.docs
    index = {"user_id": USER, "card_id": "c1"}
    assert cards.create("#artifacts", "artifact", index)
    assert cards.get("#artifacts", "artifact") == index
    for method in [cards.create, cards.put]:
        with pytest.raises(PermissionError):
            method("#artifacts", "artifact", {"user_id": OTHER})
    path = next(iter(db.docs))
    db.docs[path]["payload"] = '{"user_id":"u_other"}'
    closed(lambda: cards.get("#artifacts", "artifact"))


@pytest.mark.parametrize("error", [gexc.PermissionDenied, gexc.Conflict, gexc.Aborted, gexc.ServiceUnavailable])
def test_io_errors_sanitized_for_every_operation(error, caplog):
    db = DB()
    cards, stops = stores(db)
    cards.create(USER, "card", VALUE)
    stops.add(USER, "card")
    db.failure = error(SECRET)
    for call in [
        lambda: cards.get(USER, "card"),
        lambda: cards.create(USER, "card", VALUE),
        lambda: cards.put(USER, "card", VALUE),
        lambda: stops.add(USER, "card"),
        stops.pending,
        lambda: stops.remove(USER, "card"),
    ]:
        closed(call)
    assert SECRET not in caplog.text


@pytest.mark.parametrize("payload", ["invalid-json", "[]", "null", '{"x":NaN}'])
def test_malformed_stored_json_fails_closed(payload):
    db = DB()
    cards, _ = stores(db)
    cards.create(USER, "card", VALUE)
    db.docs[next(iter(db.docs))]["payload"] = payload
    closed(lambda: cards.get(USER, "card"))
