"""PROD-WIRE slice 3, security review round 1: the stricter guard of `tilo_api.prod.firestore_client`, its cache key,
the access store's uid and error handling, the routes' mapping of both, and the access door's build backoff.
Helpers: `_pw3_lib.py`. No emulator, no real client.

Rules pinned here (each is a test below):
- Deployed means `K_SERVICE` is non-empty; only then does a live project open. `K_SERVICE=` (empty) on a laptop with
  credentials is not Cloud Run.
- `K_SERVICE` or `CLOUD_RUN_JOB` present (even empty) refuses any `FIRESTORE_EMULATOR_HOST` that is present (even
  empty): the Firestore library enters emulator mode whenever the variable exists.
- The cached client is keyed by the project and the emulator host (or none).
- A uid Firestore refuses as a document id is a `ValueError` before any path is built.
- A Google API error from the store is `FirestoreUnavailable`, never echoed; routes answer 503, never 500.
- `deps.get_access_store` backs off after a failed client build like `deps.get_people_stores` (FS-18).
"""

from __future__ import annotations

import logging

import pytest
from _pw3_lib import DEMO, EMULATOR, PROJECT, SENTINEL, Builder, FakeClient
from fastapi import HTTPException
from fastapi.testclient import TestClient
from google.api_core import exceptions as gexc
from google.auth import exceptions as gauth_exc
from tilo_api import app, deps


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


# -- the guard ------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("variable", ["K_SERVICE", "CLOUD_RUN_JOB"])
@pytest.mark.parametrize("name", ["tilo-api", ""], ids=["named", "empty"])
@pytest.mark.parametrize("emulator", [EMULATOR, ""], ids=["host", "empty-host"])
@pytest.mark.parametrize("project", [PROJECT, DEMO])
def test_PROD_WIRE_3_a_managed_runtime_refuses_any_present_emulator_host(pw3, variable, name, emulator, project):
    builder = Builder()
    prod = pw3.use(builder)
    pw3.env(**{variable: name, "FIRESTORE_EMULATOR_HOST": emulator})
    with pytest.raises(prod.FirestoreNotConfigured):
        prod.firestore_client(project)
    assert builder.calls == [] and pw3.real.calls == []


def test_PROD_WIRE_3_a_cloud_run_job_with_an_emulator_and_a_demo_project_is_refused(pw3):
    builder = Builder()
    prod = pw3.use(builder)
    pw3.laptop(DEMO, CLOUD_RUN_JOB="tilo-job")
    with pytest.raises(prod.FirestoreNotConfigured):
        prod.firestore_client(DEMO)
    assert builder.calls == []


def test_PROD_WIRE_3_an_empty_k_service_on_a_laptop_with_a_live_project_is_refused(pw3):
    """`K_SERVICE=` is not Cloud Run: a laptop with application default credentials never reaches a live project."""
    builder = Builder()
    prod = pw3.use(builder)
    pw3.env(K_SERVICE="")
    with pytest.raises(prod.FirestoreNotConfigured):
        prod.firestore_client(PROJECT)
    assert builder.calls == [] and pw3.real.calls == []


def test_PROD_WIRE_3_a_non_empty_k_service_still_opens_a_live_project(pw3):
    builder = Builder()
    prod = pw3.use(builder)
    pw3.env(K_SERVICE="tilo-api")
    assert prod.firestore_client(PROJECT) is builder.returned[0]


def test_PROD_WIRE_3_a_cloud_run_job_alone_opens_no_live_project(pw3):
    builder = Builder()
    prod = pw3.use(builder)
    pw3.env(CLOUD_RUN_JOB="tilo-job")
    with pytest.raises(prod.FirestoreNotConfigured):
        prod.firestore_client(PROJECT)
    assert builder.calls == []


# -- the cache key ----------------------------------------------------------------------------------------------------


def test_PROD_WIRE_3_the_cache_is_keyed_by_project_and_emulator_host(pw3):
    builder = Builder()
    prod = pw3.use(builder)
    pw3.laptop(DEMO, emulator="127.0.0.1:8080")
    first = prod.firestore_client(DEMO)
    pw3.env(FIRESTORE_EMULATOR_HOST="127.0.0.1:9")  # another emulator: another client
    second = prod.firestore_client(DEMO)
    assert second is not first and builder.calls == [DEMO, DEMO]
    assert prod.firestore_client(DEMO) is second and builder.calls == [DEMO, DEMO]
    pw3.env(FIRESTORE_EMULATOR_HOST="127.0.0.1:8080")  # back: the first client again, not a third build
    assert prod.firestore_client(DEMO) is first and builder.calls == [DEMO, DEMO]


def test_PROD_WIRE_3_an_emulator_client_is_never_returned_once_the_environment_names_none(pw3):
    builder = Builder()
    prod = pw3.use(builder)
    pw3.laptop(DEMO)
    held = prod.firestore_client(DEMO)
    pw3.monkeypatch.delenv("FIRESTORE_EMULATOR_HOST")
    with pytest.raises(prod.FirestoreNotConfigured):
        prod.firestore_client(DEMO)
    pw3.env(K_SERVICE="tilo-api", GOOGLE_CLOUD_PROJECT=DEMO)  # Cloud Run, same project id, no emulator
    other = prod.firestore_client(DEMO)
    assert other is not held and builder.calls == [DEMO, DEMO]


# -- the access store's uid and errors ---------------------------------------------------------------------

BAD_UIDS = [
    "",
    ".",
    "..",
    "____",
    "__name__",
    "__x__",
    "a/b",
    "/",
    "a" * 1501,
    "é" * 751,  # 1502 bytes
    "\ud800",  # not encodable as UTF-8
]
GOOD_UIDS = ["u_pw3", "__", "___", "a" * 1500, "é" * 750, "...", ".a", "a.", "__a", "a__", "_a_", "u-1.2"]


def _store(pw3, client=None, **kwargs):
    prod = pw3.use()
    return prod.FirestoreAccessStore(client if client is not None else FakeClient(), **kwargs)


@pytest.mark.parametrize("uid", BAD_UIDS, ids=lambda u: f"len{len(u)}-{u[:6]!r}")
def test_PROD_WIRE_3_SEC_15_a_uid_firestore_refuses_as_a_document_id_is_a_value_error_before_any_path(pw3, uid):
    client = FakeClient()
    store = _store(pw3, client)
    with pytest.raises(ValueError):
        store.get(uid)
    with pytest.raises(ValueError):
        store.declare(uid, "judge")
    assert client.ops == [] and client.docs == {}


@pytest.mark.parametrize("uid", GOOD_UIDS, ids=lambda u: f"len{len(u)}-{u[:6]!r}")
def test_PROD_WIRE_3_SEC_15_a_uid_firestore_accepts_still_works(pw3, uid):
    store = _store(pw3)
    assert store.declare(uid, "visitor") == "visitor" and store.get(uid) == "visitor"


LIBRARY_ERRORS = [
    lambda: gexc.ServiceUnavailable(f"unavailable ({SENTINEL})"),
    lambda: gexc.PermissionDenied(f"denied ({SENTINEL})"),
    lambda: gexc.DeadlineExceeded(f"slow ({SENTINEL})"),
    lambda: gexc.RetryError(f"retries ({SENTINEL})", cause=None),
    lambda: gauth_exc.RefreshError(f"refresh ({SENTINEL})"),
    lambda: gauth_exc.TransportError(f"transport ({SENTINEL})"),
]
LIBRARY_IDS = ["unavailable", "permission-denied", "deadline", "retry-error", "auth-refresh", "auth-transport"]


@pytest.fixture
def failing(pw3, monkeypatch):
    """`failing(op, error)`: every `_Ref.<op>` of the fake client raises `error()`."""
    import _pw3_lib

    def install(op, error):
        def boom(self, *args, **kwargs):
            raise error()

        monkeypatch.setattr(_pw3_lib._Ref, op, boom)

    return install


@pytest.mark.parametrize("error", LIBRARY_ERRORS, ids=LIBRARY_IDS)
def test_PROD_WIRE_3_SEC_15_a_library_error_on_get_is_firestore_unavailable_and_never_echoed(
    pw3, failing, error, caplog
):
    store = _store(pw3)
    failing("get", error)
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(pw3.use().FirestoreUnavailable) as caught:
            store.get("u_pw3")
    assert (caught.value.status_code, caught.value.detail) == (503, "store_unavailable")
    assert SENTINEL not in str(caught.value) and SENTINEL not in repr(caught.value)
    assert SENTINEL not in caplog.text


@pytest.mark.parametrize("error", LIBRARY_ERRORS, ids=LIBRARY_IDS)
def test_PROD_WIRE_3_SEC_15_a_library_error_on_create_is_firestore_unavailable_and_never_echoed(
    pw3, failing, error, caplog
):
    client = FakeClient()
    store = _store(pw3, client)
    failing("create", error)
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(pw3.use().FirestoreUnavailable) as caught:
            store.declare("u_pw3", "judge")
    assert SENTINEL not in str(caught.value) and SENTINEL not in caplog.text
    assert client.docs == {}


@pytest.mark.parametrize("error", LIBRARY_ERRORS, ids=LIBRARY_IDS)
def test_PROD_WIRE_3_SEC_15_a_library_error_on_the_read_back_is_firestore_unavailable(pw3, failing, error, caplog):
    client = FakeClient({"orgs/org_tilo/access/u_pw3": {"declaration": "judge"}})
    store = _store(pw3, client)
    failing("get", error)  # create meets the stored document (AlreadyExists), then the read-back fails
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(pw3.use().FirestoreUnavailable):
            store.declare("u_pw3", "visitor")
    assert SENTINEL not in caplog.text
    assert client.docs["orgs/org_tilo/access/u_pw3"] == {"declaration": "judge"}


# -- the routes never answer 500 ---------------------------------------------------------------------------


@pytest.fixture
def routes(pw3):
    """`routes(uid, client)` -> a TestClient on the real app with that principal and a Firestore access store over
    `client` (not deployed, so the gate is off and only the route's own handling is under test)."""
    saved = dict(app.dependency_overrides)

    def make(uid, client):
        store = pw3.use().FirestoreAccessStore(client)
        app.dependency_overrides[deps.get_current_principal] = lambda: deps.Principal(user_id=uid, role="owner")
        app.dependency_overrides[deps.get_access_store] = lambda: store
        return TestClient(app, raise_server_exceptions=True)

    yield make
    app.dependency_overrides.clear()
    app.dependency_overrides.update(saved)


@pytest.mark.parametrize("uid", ["a/b", "..", "__x__"])
def test_PROD_WIRE_3_SEC_15_a_uid_the_store_refuses_is_a_503_on_both_routes_never_a_500(routes, uid):
    client = routes(uid, FakeClient())
    read = client.get("/access")
    write = client.post("/access/declaration", json={"declaration": "judge"})
    for response in (read, write):
        assert response.status_code == 503, response.text
        assert uid not in response.text


@pytest.mark.parametrize("error", LIBRARY_ERRORS, ids=LIBRARY_IDS)
def test_PROD_WIRE_3_SEC_15_a_library_error_is_a_503_store_unavailable_on_both_routes_never_echoed(
    routes, failing, error
):
    failing("get", error)
    failing("create", error)
    client = routes("u_pw3", FakeClient())
    for response in (client.get("/access"), client.post("/access/declaration", json={"declaration": "judge"})):
        assert response.status_code == 503, response.text
        assert response.json()["detail"] == "store_unavailable"
        assert SENTINEL not in response.text


# -- the access door's build backoff ----------------------------------------------------------------------------------


def test_PROD_WIRE_3_SEC_15_a_failed_client_build_backs_off_the_access_door_like_the_people_door(pw3):
    builder, clock = Builder(make=FakeClient), FakeClock()
    builder.fail = True
    pw3.use(builder)
    pw3.monkeypatch.setattr(deps, "people_stores_clock", clock, raising=False)
    pw3.deployed(PROJECT, api=True)
    with pytest.raises(HTTPException) as first:
        deps.get_access_store()
    assert first.value.status_code == 503 and SENTINEL not in str(first.value.detail)
    assert builder.calls == [PROJECT]
    builder.fail = False  # the metadata server is back, but the window has not passed
    for _ in range(3):
        with pytest.raises(HTTPException) as inside:
            deps.get_access_store()
        assert inside.value.status_code == 503 and SENTINEL not in str(inside.value.detail)
    assert builder.calls == [PROJECT], "inside the window: refused at once, no client call"
    clock.now += deps.PEOPLE_STORES_BACKOFF_S + 1
    assert deps.get_access_store().get("u_pw3") is None and builder.calls == [PROJECT, PROJECT]
    assert deps.get_access_store().get("u_pw3") is None  # a success clears the window
    assert builder.calls == [PROJECT, PROJECT]


def test_PROD_WIRE_3_SEC_15_a_not_configured_refusal_is_not_backed_off(pw3):
    builder, clock = Builder(make=FakeClient), FakeClock()
    pw3.use(builder)
    pw3.monkeypatch.setattr(deps, "people_stores_clock", clock, raising=False)
    pw3.deployed(PROJECT)  # no TILO_API_STORE
    for _ in range(2):
        with pytest.raises(HTTPException) as refused:
            deps.get_access_store()
        assert (refused.value.status_code, refused.value.detail) == (503, "not_configured")
    pw3.env(TILO_API_STORE="firestore")  # configured now, same instant: opens at once
    assert deps.get_access_store().get("u_pw3") is None and builder.calls == [PROJECT]


def test_PROD_WIRE_3_SEC_15_a_cold_process_has_no_access_backoff(pw3):
    """`deps.get_people_stores.cache_clear()` is the tests' cold-process reset: it forgets the access window too."""
    builder, clock = Builder(make=FakeClient), FakeClock()
    builder.fail = True
    pw3.use(builder)
    pw3.monkeypatch.setattr(deps, "people_stores_clock", clock, raising=False)
    pw3.deployed(PROJECT, api=True)
    with pytest.raises(HTTPException):
        deps.get_access_store()
    deps.get_people_stores.cache_clear()
    builder.fail = False
    assert deps.get_access_store().get("u_pw3") is None
