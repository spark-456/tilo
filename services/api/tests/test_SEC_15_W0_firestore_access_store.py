"""SEC-15 W0 (completion plan, 9 Oct): the AccessGate answered 503 on every route on tilo-dev because
`deps.get_access_store` had no production store. `FirestoreAccessStore` keeps each person's declaration at
`access/{user_id}` and honours the contract written on `AccessStore.declare`: one create-if-absent (create the
document; on AlreadyExists read it back), never read-then-write, never an overwrite, so two concurrent first calls
leave exactly one winner and a stored declaration is never changed by a request. `deps.get_access_store` opens it
through the same door as every other durable store (`store_door`: `TILO_API_STORE=firestore` plus a valid project;
anything else is 503 `not_configured`, never a fallback to memory).

No network and no credentials: the Firestore client is the in-memory fake the people-store tests use."""

from __future__ import annotations

import threading

import pytest
from _ppl11c_fs_fake import FakeFirestore
from fastapi import HTTPException

USER = "u_" + "a" * 48
OTHER = "u_" + "b" * 48
PATH = f"access/{USER}"


def store_over(db: FakeFirestore):
    from tilo_api.access_firestore import FirestoreAccessStore

    return FirestoreAccessStore(db)


def test_SEC_15_W0_a_declaration_is_one_document_holding_only_the_choice():
    db = FakeFirestore()
    assert store_over(db).declare(USER, "judge") == "judge"
    stored = db.raw(PATH)
    assert stored is not None
    assert stored["declaration"] == "judge"
    assert set(stored) <= {"declaration", "declared_at"}, "no email, name or other person data is kept here"


def test_SEC_15_W0_nothing_stored_means_nothing_declared():
    assert store_over(FakeFirestore()).get(USER) is None


def test_SEC_15_W0_what_was_declared_is_read_back():
    store = store_over(FakeFirestore())
    store.declare(USER, "visitor")
    assert store.get(USER) == "visitor"
    assert store.get(OTHER) is None


def test_SEC_15_W0_first_write_wins_and_a_second_different_call_gets_the_first_value():
    db = FakeFirestore()
    store = store_over(db)
    assert store.declare(USER, "visitor") == "visitor"
    assert store.declare(USER, "judge") == "visitor"
    assert db.raw(PATH)["declaration"] == "visitor"


def test_SEC_15_W0_only_create_is_ever_attempted_never_a_set_update_or_delete():
    db = FakeFirestore()
    store = store_over(db)
    store.declare(USER, "visitor")
    store.declare(USER, "judge")
    assert {kind for kind, _ in db.attempted_ops} == {"create"}


def test_SEC_15_W0_a_rival_that_wrote_first_is_read_back_and_not_overwritten():
    db = FakeFirestore()
    db.put(PATH, {"declaration": "judge"})  # another instance of the service declared between our read and our create
    assert store_over(db).declare(USER, "visitor") == "judge"
    assert db.raw(PATH) == {"declaration": "judge"}


def test_SEC_15_W0_many_concurrent_first_calls_leave_exactly_one_winner():
    db = FakeFirestore()
    store = store_over(db)
    answers: list[str] = []
    barrier = threading.Barrier(16)

    def go(choice: str) -> None:
        barrier.wait()
        answers.append(store.declare(USER, choice))  # type: ignore[arg-type]

    threads = [threading.Thread(target=go, args=("visitor" if i % 2 else "judge",)) for i in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(set(answers)) == 1, "every caller is told the one winning value"
    assert db.raw(PATH)["declaration"] == answers[0]


@pytest.mark.parametrize("bad", ["admin", "", None, 1, ["judge"], "Judge"])
def test_SEC_15_W0_a_stored_value_outside_the_two_choices_is_never_trusted(bad):
    db = FakeFirestore()
    db.put(PATH, {"declaration": bad})
    store = store_over(db)
    with pytest.raises(Exception, match="declaration"):
        store.get(USER)  # the gate turns any store failure into 503: nothing is let through on a guess


@pytest.mark.parametrize("uid", ["", "u_", "../x", "u_a/b", "u_a\n", "u_" + "a" * 49, "x_" + "a" * 10, "u_é"])
def test_SEC_15_W0_a_user_id_that_is_not_a_user_id_never_becomes_a_path(uid):
    db = FakeFirestore()
    store = store_over(db)
    with pytest.raises(ValueError):
        store.get(uid)
    with pytest.raises(ValueError):
        store.declare(uid, "visitor")
    assert db.attempted_ops == []


def test_SEC_15_W0_an_unknown_choice_is_refused_before_anything_is_written():
    db = FakeFirestore()
    with pytest.raises(ValueError):
        store_over(db).declare(USER, "admin")  # type: ignore[arg-type]
    assert db.attempted_ops == []


def test_SEC_15_W0_a_failing_backend_surfaces_as_an_error_not_as_no_declaration():
    class Down(FakeFirestore):
        def document(self, path):
            raise RuntimeError("firestore is down")

    store = store_over(Down())
    with pytest.raises(RuntimeError):
        store.get(USER)
    with pytest.raises(RuntimeError):
        store.declare(USER, "judge")


# -- the seam ---------------------------------------------------------------------------------------------------------

CONFIG = {
    "TILO_API_STORE": "firestore",
    "TILO_FIRESTORE_PROJECT": "demo-tilo",
    "FIRESTORE_EMULATOR_HOST": "localhost:8080",
}


def test_SEC_15_W0_deployed_without_a_firestore_config_the_seam_is_503_not_configured(monkeypatch):
    from tilo_api import access_firestore, deps

    for name in CONFIG:
        monkeypatch.delenv(name, raising=False)
    access_firestore.reset_for_tests()
    with pytest.raises(HTTPException) as caught:
        deps.get_access_store()
    assert (caught.value.status_code, caught.value.detail) == (503, "not_configured")


def test_SEC_15_W0_memory_is_never_a_fallback(monkeypatch):
    from tilo_api import access_firestore, deps

    monkeypatch.setenv("TILO_API_STORE", "memory")
    monkeypatch.setenv("TILO_FIRESTORE_PROJECT", "demo-tilo")
    access_firestore.reset_for_tests()
    with pytest.raises(HTTPException) as caught:
        deps.get_access_store()
    assert caught.value.status_code == 503


def test_SEC_15_W0_with_the_config_the_seam_is_the_firestore_store_over_one_cached_client(monkeypatch):
    from tilo_api import access_firestore, deps

    for name, value in CONFIG.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("K_SERVICE", raising=False)
    made: list[str] = []
    db = FakeFirestore()
    monkeypatch.setattr(access_firestore, "client_factory", lambda project: made.append(project) or db)
    access_firestore.reset_for_tests()
    first = deps.get_access_store()
    assert isinstance(first, access_firestore.FirestoreAccessStore)
    assert deps.get_access_store() is first, "one store per config, one client"
    assert made == ["demo-tilo"]
    first.declare(USER, "judge")
    assert db.raw(PATH)["declaration"] == "judge"


def test_SEC_15_W0_the_gate_lets_a_declared_judge_through_on_a_deployed_process(monkeypatch):
    """End to end through the real gate: before W0 this was 503 for everybody."""
    from fastapi.testclient import TestClient
    from tilo_api import app, deps

    monkeypatch.setenv("K_SERVICE", "tilo-api")
    store = store_over(FakeFirestore())
    app.dependency_overrides[deps.get_access_store] = lambda: store
    app.dependency_overrides[deps.get_current_principal] = lambda: deps.Principal(
        user_id=USER, role="owner", world_id=None
    )
    try:
        client = TestClient(app)
        assert client.get("/access").status_code == 200
        before = client.get("/costs")
        assert before.status_code == 403 and before.json()["code"] == "declaration_required"
        assert client.post("/access/declaration", json={"declaration": "judge"}).status_code in (200, 201)
        assert store.get(USER) == "judge"
        assert client.get("/costs").status_code != 403
    finally:
        app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _fresh_seam():
    from tilo_api import access_firestore

    access_firestore.reset_for_tests()
    yield
    access_firestore.reset_for_tests()  # a cached fake store never leaks into another test


def test_SEC_15_W0_nothing_declared_is_never_remembered():
    db = FakeFirestore()
    store = store_over(db)
    assert store.get(USER) is None
    db.put(PATH, {"declaration": "judge"})  # declared on another instance meanwhile
    assert store.get(USER) == "judge"


def test_SEC_15_W0_the_remembered_answers_stay_bounded():
    from tilo_api import access_firestore

    db = FakeFirestore()
    store = store_over(db)
    for n in range(access_firestore._REMEMBERED + 50):
        uid = f"u_{n:048d}"
        db.put(f"access/{uid}", {"declaration": "visitor"})
        store.get(uid)
    assert len(store._seen) <= access_firestore._REMEMBERED


def test_SEC_15_W0_a_document_that_vanishes_after_AlreadyExists_is_an_error_not_a_guess():
    from google.api_core import exceptions as gexc

    class Vanishing(FakeFirestore):
        def document(self, path):
            ref = super().document(path)

            def create(_data):
                raise gexc.AlreadyExists("exists")

            ref.create = create  # type: ignore[method-assign]
            return ref

    with pytest.raises(RuntimeError):
        store_over(Vanishing()).declare(USER, "judge")
