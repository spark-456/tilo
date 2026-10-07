"""PROD-WIRE slice 3, part 3 (unit): `tilo_api.prod.FirestoreAccessStore` (SEC-15's declaration kept in Firestore) and
`deps.get_access_store`. The emulator half is `test_PROD_WIRE_3_access_store_emulator.py`. Helpers: `_pw3_lib.py`.

The fake client (`_pw3_lib.FakeClient`) has Firestore's own write rule for `create` (`AlreadyExists` when the document
exists) and records, then refuses, every other write method: a store that calls `set`, `update`, `delete`, a
transaction or a batch fails here. `AccessStore.declare` (tilo_api/access.py): first write wins, one create-if-absent,
on `AlreadyExists` read it back, never an overwrite.

Ambiguity resolved: a stored value that is not "visitor" or "judge" reads as None (fail closed, the brief); what
`declare` answers when AlreadyExists is followed by such a malformed document is not pinned here (the brief says
"returns the stored value"; there is none to return).
"""

from __future__ import annotations

import pytest
from _pw3_lib import PROJECT, Builder, FakeClient, threads
from fastapi import HTTPException
from fastapi.testclient import TestClient
from tilo_api import app, deps

UID, OTHER = "u_pw3_judge", "u_pw3_other"


def _store(pw3, client=None, **kwargs):
    prod = pw3.use()
    return prod.FirestoreAccessStore(client if client is not None else FakeClient(), **kwargs)


def test_PROD_WIRE_3_SEC_15_a_stored_declaration_is_read_back_from_orgs_org_access_uid(pw3):
    client = FakeClient({f"orgs/org_tilo/access/{UID}": {"declaration": "judge"}})
    store = _store(pw3, client)
    assert store.get(UID) == "judge"
    assert store.get(OTHER) is None, "nothing stored: None, not an error"
    assert callable(store.declare)


def test_PROD_WIRE_3_SEC_15_the_org_is_a_parameter_and_part_of_the_path(pw3):
    client = FakeClient({f"orgs/org_other/access/{UID}": {"declaration": "visitor"}})
    assert _store(pw3, client, org_id="org_other").get(UID) == "visitor"
    assert _store(pw3, client).get(UID) is None, "the default org is org_tilo"


@pytest.mark.parametrize(
    "stored",
    [
        {"declaration": "admin"},
        {"declaration": "Judge"},
        {"declaration": "judge "},
        {"declaration": ""},
        {"declaration": None},
        {"declaration": 1},
        {"declaration": ["judge"]},
        {"declaration": {"value": "judge"}},
        {"role": "judge"},
        {},
    ],
)
def test_PROD_WIRE_3_SEC_15_a_malformed_stored_declaration_reads_as_none(pw3, stored):
    store = _store(pw3, FakeClient({f"orgs/org_tilo/access/{UID}": stored}))
    assert store.get(UID) is None, "fail closed: only the exact strings visitor and judge are a declaration"


@pytest.mark.parametrize("value", ["judge", "visitor"])
def test_PROD_WIRE_3_SEC_15_the_first_declaration_is_created_and_returned(pw3, value):
    client = FakeClient()
    store = _store(pw3, client)
    assert store.declare(UID, value) == value
    path = f"orgs/org_tilo/access/{UID}"
    assert list(client.docs) == [path] and client.docs[path]["declaration"] == value, "one document, one field"
    assert [op for op, _ in client.ops if op == "create"] == ["create"], "one create"
    assert store.get(UID) == value


def test_PROD_WIRE_3_SEC_15_first_write_wins_and_a_second_different_declare_returns_the_first(pw3):
    client = FakeClient()
    store = _store(pw3, client)
    assert store.declare(UID, "visitor") == "visitor"
    assert store.declare(UID, "judge") == "visitor", "the stored value, not the new one"
    assert store.declare(UID, "visitor") == "visitor"
    assert store.get(UID) == "visitor"
    assert client.docs[f"orgs/org_tilo/access/{UID}"]["declaration"] == "visitor"
    assert client.writes() == []


def test_PROD_WIRE_3_SEC_15_declare_never_overwrites_it_only_creates_and_reads_back(pw3):
    client = FakeClient({f"orgs/org_tilo/access/{UID}": {"declaration": "judge"}})
    store = _store(pw3, client)
    assert store.declare(UID, "visitor") == "judge"
    assert client.writes() == [], f"no set, update, delete, transaction or batch: {client.writes()}"
    assert client.docs[f"orgs/org_tilo/access/{UID}"] == {"declaration": "judge"}


def test_PROD_WIRE_3_SEC_15_eight_concurrent_first_declares_leave_exactly_one_winner(pw3):
    client = FakeClient(read_delay=0.01)  # a read-then-write store would race here
    store = _store(pw3, client)
    values = ["judge", "visitor"] * 4
    results = threads(8, lambda i: store.declare(UID, values[i]))
    assert not [r for r in results if isinstance(r, BaseException)], results
    assert len(set(results)) == 1, f"every caller gets the same stored value: {results}"
    assert client.docs[f"orgs/org_tilo/access/{UID}"]["declaration"] == results[0]
    assert client.writes() == []


@pytest.mark.parametrize("uid", ["", "a/b", "/", "u_pw3/", "orgs/org_tilo/access/x"])
def test_PROD_WIRE_3_SEC_15_an_empty_uid_or_one_with_a_slash_is_refused_before_any_client_call(pw3, uid):
    client = FakeClient()
    store = _store(pw3, client)
    with pytest.raises(ValueError):
        store.get(uid)
    with pytest.raises(ValueError):
        store.declare(uid, "judge")
    assert client.ops == [] and client.docs == {}, "no document path is even built"


def test_PROD_WIRE_3_SEC_15_get_access_store_returns_a_firestore_access_store_on_the_shared_client(pw3):
    from tilo_api import durable_store

    builder = Builder(make=FakeClient)
    prod = pw3.use(builder)
    pw3.deployed(PROJECT, api=True)
    store = deps.get_access_store()
    assert isinstance(store, prod.FirestoreAccessStore)
    assert store.declare(UID, "judge") == "judge" and store.get(UID) == "judge"
    client = builder.returned[0]
    assert client.docs == {f"orgs/{deps.ORG_ID}/access/{UID}": {"declaration": "judge"}}, "on the shared client"
    durable_store.deployed()  # the api store, on the same process-wide client
    assert deps.get_access_store().get(UID) == "judge"
    assert builder.calls == [PROJECT]


@pytest.mark.parametrize(
    "config",
    [
        {},
        {"TILO_API_STORE": "memory"},
        {"TILO_API_STORE": "firestore", "TILO_FIRESTORE_PROJECT": "Not A Project"},
        {"TILO_PEOPLE_STORE": "firestore"},
    ],
    ids=["no-config", "memory", "bad-project", "people-switch-only"],
)
def test_PROD_WIRE_3_SEC_15_without_the_api_store_switch_the_access_store_is_503_not_configured_and_never_cached(
    pw3, config
):
    builder = Builder(make=FakeClient)
    pw3.use(builder)
    pw3.deployed(PROJECT, **{k: v for k, v in config.items() if k == "TILO_PEOPLE_STORE"})
    for name, value in config.items():
        pw3.env(**{name: value})
    for _ in range(2):
        with pytest.raises(HTTPException) as refused:
            deps.get_access_store()
        assert (refused.value.status_code, refused.value.detail) == (503, "not_configured")
    assert builder.calls == []
    pw3.env(TILO_API_STORE="firestore", TILO_FIRESTORE_PROJECT=PROJECT)  # configured later: no stale refusal
    assert deps.get_access_store().get(UID) is None and builder.calls == [PROJECT]


def test_PROD_WIRE_3_SEC_15_a_failing_client_build_is_a_503_that_never_echoes_the_error(pw3):
    builder = Builder(make=FakeClient)
    builder.fail = True
    pw3.use(builder)
    pw3.deployed(PROJECT, api=True)
    # Security round 1 (restated): a failed build is remembered for the FS-18 window (test_PROD_WIRE_3_security_round1
    # pins the window itself); the next request after it tries again.
    now = [1000.0]
    pw3.monkeypatch.setattr(deps, "people_stores_clock", lambda: now[0], raising=False)
    with pytest.raises(HTTPException) as refused:
        deps.get_access_store()
    assert refused.value.status_code == 503 and "cannot reach" not in str(refused.value.detail)
    builder.fail = False
    now[0] += deps.PEOPLE_STORES_BACKOFF_S + 1
    assert deps.get_access_store().get(UID) is None  # the next request tries again


def test_PROD_WIRE_3_SEC_15_the_declaration_routes_run_on_the_firestore_store_without_an_override(pw3):
    """`POST /access/declaration` and `GET /access`, deployed, the real app and the real seam: set once, then locked."""
    builder = Builder(make=FakeClient)
    pw3.use(builder)
    pw3.deployed(PROJECT, api=True)
    saved = dict(app.dependency_overrides)
    app.dependency_overrides.clear()
    app.dependency_overrides[deps.get_current_principal] = lambda: deps.Principal(user_id=UID, role="owner")
    try:
        client = TestClient(app, raise_server_exceptions=True)
        first = client.post("/access/declaration", json={"declaration": "judge"})
        assert first.status_code == 200, first.text
        assert first.json()["declaration"] == "judge" and first.json()["allowed"] is True
        again = client.post("/access/declaration", json={"declaration": "visitor"})
        assert (again.status_code, again.json()["code"]) == (409, "declaration_locked")
        assert client.get("/access").json()["declaration"] == "judge"
        stored = builder.returned[0].docs
        assert stored == {f"orgs/{deps.ORG_ID}/access/{UID}": {"declaration": "judge"}}
        assert builder.calls == [PROJECT]
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(saved)
