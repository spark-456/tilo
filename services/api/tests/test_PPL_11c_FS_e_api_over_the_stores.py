"""PPL-11c-FS FS-14 (the people API's directory routes over the stores: atomic with no process lock, on `MemoryStore`
with a slow `list` and on the Firestore emulator) and FS-15 (a regression guard for issue #541 item 4a). Spec:
`API_PPL_11c_FS.md` section 6.

Issue #541 item 4b: removing `_DIRECTORY_LOCK` from `create_first_person` still passed the 8-thread race test,
because the in-memory store is fast. The memory tests here neutralise the lock (`monkeypatch` to a null context; the
attribute may be gone once the builder deletes it, hence `raising=False`) and hand the API a person store whose `get`
and `list` read a snapshot and then sleep 100 ms, so a check-then-create in the API (rather than one atomic store
call) is certain to interleave.
"""

from __future__ import annotations

import contextlib
import dataclasses
import time

import pytest
from _ppl11a_lib import OWNER, PRIYA, SAM, run_threads
from _ppl11c_fs_lib import email_path, founder_path, person, raw, unique_org
from _ppl11c_lib import PERSON_BODY, R_PERSON_FIRST, WORK_ITEM_BODY
from fastapi import Request
from fastapi.testclient import TestClient
from tilo_people.stores import erase_person

emulator = pytest.mark.emulator
FOUNDER = "u_founder"


def _body(**changes):
    return {**PERSON_BODY, **changes}


class SlowPersons:
    """A person store whose reads take a snapshot and then sleep before they answer, so the answer is stale by the
    time the caller acts on it (as a database read is); every other call goes straight through."""

    def __init__(self, inner, delay: float = 0.1) -> None:
        self._inner, self._delay = inner, delay

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def get(self, *args, **kwargs):
        answer = self._inner.get(*args, **kwargs)
        time.sleep(self._delay)
        return answer

    def list(self, *args, **kwargs):
        answer = self._inner.list(*args, **kwargs)
        time.sleep(self._delay)
        return answer


def _slow(rig):
    rig.stores = dataclasses.replace(rig.stores, persons=SlowPersons(rig.stores.persons))


def _no_process_lock(monkeypatch):
    monkeypatch.setattr("tilo_api.people_writes._DIRECTORY_LOCK", contextlib.nullcontext(), raising=False)


def _principal_from_header(rig):
    def principal(request: Request):
        return rig.deps.Principal(user_id=request.headers["x-test-user"], role="owner")

    rig.app.dependency_overrides[rig.deps.get_current_principal] = principal


def _race_http(rig, work, callers: int = 8):
    """`work(client, i)` on `callers` threads released together. The clients are started BEFORE the race (a client
    that starts inside it staggers its request by tens of milliseconds and the callers no longer overlap)."""
    with contextlib.ExitStack() as stack:
        clients = [stack.enter_context(TestClient(rig.app, raise_server_exceptions=False)) for _ in range(callers)]
        return run_threads(callers, lambda i: work(clients[i], i))


def _claim_first(rig, callers: int = 8):
    """Eight strangers `u_f{i}` claim the org at once: the status codes."""

    def claim(client, i: int) -> int:
        body = _body(email=f"founder{i}@example.com", display_name=f"Founder {i}")
        return client.post("/v1/people/first", json=body, headers={"x-test-user": f"u_f{i}"}).status_code

    return _race_http(rig, claim, callers)


def _create_same_address(rig, callers: int = 8):
    """Org owners `u_o{i}` each add a person with the one address all eight use: (status, code) per caller. Eight
    principals, not one: the write limiter serialises one principal's requests, which would hide the race."""

    def create(client, i: int):
        response = client.post("/v1/people", json=_body(display_name=f"Nina {i}"), headers={"x-test-user": f"u_o{i}"})
        return response.status_code, response.json().get("code")

    return _race_http(rig, create, callers)


# --- FS-14: the routes need no process lock --------


def test_PPL_11c_FS_14_eight_founders_with_a_slow_store_and_no_process_lock_leave_one(people_rig, monkeypatch):
    rig = people_rig()
    rig.require_route(R_PERSON_FIRST)
    _no_process_lock(monkeypatch)
    _slow(rig)
    _principal_from_header(rig)
    statuses = _claim_first(rig)
    assert sorted(statuses) == [201] + [403] * 7, statuses
    persons = [s.record for s in rig.real.persons.list(rig.org)]
    assert len(persons) == 1 and persons[0]["org_role"] == "owner"
    assert rig.real.persons.founded(rig.org) is True


def test_PPL_11c_FS_14_eight_creates_of_one_address_with_a_slow_store_and_no_process_lock_leave_one(
    people_rig, monkeypatch
):
    rig = people_rig()
    rig.add_people([person(f"u_o{i}", rig.org, role="owner", email=f"o{i}@example.com") for i in range(8)])
    rig.require_route(("POST", "/v1/people"))
    _no_process_lock(monkeypatch)
    _slow(rig)
    _principal_from_header(rig)
    count = len(rig.real.persons.list(rig.org))
    results = _create_same_address(rig)
    assert sorted(code for code, _ in results) == [201] + [409] * 7, results
    assert {name for code, name in results if code == 409} == {"email_taken"}
    assert len(rig.real.persons.list(rig.org)) == count + 1


def test_PPL_11c_FS_14_an_address_taken_by_a_person_who_is_then_erased_is_free_again_over_the_api(people_rig):
    rig = people_rig()
    rig.add_people()
    rig.as_user(OWNER)
    rig.require_route(("POST", "/v1/people"))
    created = rig.post("/v1/people", _body())
    assert created.status_code == 201
    assert rig.post("/v1/people", _body(display_name="Again")).status_code == 409
    assert erase_person(rig.real, rig.org, created.json()["id"])["person"] == 1
    assert rig.post("/v1/people", _body(display_name="Again")).status_code == 201


# --- FS-14 on the emulator: the same routes over the Firestore store --------


def _fs_rig(people_rig, fs_backend):
    org = unique_org()
    rig = people_rig(org=org)
    stores = fs_backend.stores()
    rig.real = stores
    rig.stores = rig._wrap(stores)
    rig.as_user(FOUNDER)
    return rig, org, stores


@emulator
def test_PPL_11c_FS_14_first_on_firestore_writes_the_owner_the_address_and_the_founder_marker(people_rig, fs_backend):
    rig, org, stores = _fs_rig(people_rig, fs_backend)
    rig.require_route(R_PERSON_FIRST)
    created = rig.client.post("/v1/people/first", json=_body())
    assert created.status_code == 201, created.text[:300]
    assert raw(fs_backend.client, founder_path(org)) == {"uid": FOUNDER}
    assert raw(fs_backend.client, email_path(org, "nina.patel@example.com")) == {"person_id": FOUNDER}
    assert stores.persons.get(org, FOUNDER).record["org_role"] == "owner"
    rig.as_user("u_late")
    refused = rig.client.post("/v1/people/first", json=_body(email="late@example.com"))
    assert refused.status_code == 403 and refused.json() == {"detail": "forbidden"}


@emulator
@pytest.mark.parametrize("round_", range(2))
def test_PPL_11c_FS_14_racing_founders_on_firestore_leave_one(people_rig, fs_backend, monkeypatch, round_):
    rig, org, stores = _fs_rig(people_rig, fs_backend)
    rig.require_route(R_PERSON_FIRST)
    _no_process_lock(monkeypatch)
    _principal_from_header(rig)
    statuses = _claim_first(rig, 3)  # three callers: see `_ppl11c_fs_lib.racers`
    assert sorted(statuses) == [201] + [403] * 2, statuses
    persons = stores.persons.list(org)
    assert len(persons) == 1
    assert raw(fs_backend.client, founder_path(org)) == {"uid": persons[0].record["id"]}


@emulator
@pytest.mark.parametrize("round_", range(2))
def test_PPL_11c_FS_14_racing_creates_of_one_address_on_firestore_leave_one(
    people_rig, fs_backend, monkeypatch, round_
):
    rig, org, stores = _fs_rig(people_rig, fs_backend)
    for i in range(3):
        stores.persons.create(person(f"u_o{i}", org, role="owner", email=f"o{i}@example.com"))
    rig.require_route(("POST", "/v1/people"))
    _no_process_lock(monkeypatch)
    _principal_from_header(rig)
    results = _create_same_address(rig, 3)
    assert sorted(code for code, _ in results) == [201] + [409] * 2, results
    holders = [s.record["id"] for s in stores.persons.list(org) if s.record["email"] == PERSON_BODY["email"]]
    assert len(holders) == 1
    assert raw(fs_backend.client, email_path(org, PERSON_BODY["email"])) == {"person_id": holders[0]}


@emulator
def test_PPL_11c_FS_14_an_emptied_org_cannot_be_refounded_over_the_api_on_firestore(people_rig, fs_backend):
    rig, org, stores = _fs_rig(people_rig, fs_backend)
    rig.require_route(R_PERSON_FIRST)
    assert rig.client.post("/v1/people/first", json=_body()).status_code == 201
    second = rig.post("/v1/people", _body(email="second@example.com", display_name="Second"))
    assert second.status_code == 201
    assert erase_person(stores, org, FOUNDER)["person"] == 1
    assert erase_person(stores, org, second.json()["id"])["person"] == 1
    assert stores.persons.list(org) == ()
    again = rig.client.post("/v1/people/first", json=_body(email="again@example.com"))
    assert again.status_code == 403 and again.json() == {"detail": "forbidden"}


@emulator
def test_PPL_11c_FS_14_the_bootstrap_uid_gate_holds_over_firestore(people_rig, fs_backend, monkeypatch):
    for name in ("TILO_PEOPLE_BOOTSTRAP_UID", "K_SERVICE", "CLOUD_RUN_JOB", "TILO_API_DEV"):
        monkeypatch.delenv(name, raising=False)
    rig, org, stores = _fs_rig(people_rig, fs_backend)
    rig.unwire("founder_gate")
    rig.require_route(R_PERSON_FIRST)
    rig.as_user("u_other")
    assert rig.client.post("/v1/people/first", json=_body()).status_code == 403, "unconfigured is closed"
    monkeypatch.setenv("TILO_PEOPLE_BOOTSTRAP_UID", FOUNDER)
    assert rig.client.post("/v1/people/first", json=_body()).status_code == 403, "another uid"
    assert stores.persons.founded(org) is False and stores.persons.list(org) == ()
    rig.as_user(FOUNDER)
    assert rig.client.post("/v1/people/first", json=_body()).status_code == 201
    assert stores.persons.founded(org) is True


@emulator
def test_PPL_11c_FS_14_explicit_config_wires_the_emulator_stores_and_the_write_limit_spans_requests(
    people_rig, fs_backend, monkeypatch
):
    """The real wiring, no override of `get_people_stores`: `TILO_PEOPLE_STORE=firestore` plus a `demo-` project (the
    emulator host is set by the session fixture) gives the process one `PeopleStores`, so the in-memory write limiter
    that lives on it (BQ-PPL11C-2) counts across requests: 60 creates, the 61st is 429 (issue #549 item 1: a fresh
    stores object per request accepted 65 of 65)."""
    from tilo_api import deps

    for name in ("K_SERVICE", "CLOUD_RUN_JOB", "TILO_API_DEV"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TILO_PEOPLE_STORE", "firestore")
    monkeypatch.setenv("TILO_FIRESTORE_PROJECT", "demo-tilo")
    clear = getattr(deps.get_people_stores, "cache_clear", lambda: None)
    clear()
    try:
        org = unique_org()
        rig = people_rig(org=org)
        rig.unwire("people_stores")
        stores = deps.get_people_stores()
        assert deps.get_people_stores() is stores
        stores.persons.create(person(PRIYA, org, email="priya@example.com"))
        rig.as_user(PRIYA)
        rig.require_route(("POST", "/v1/work-items"))
        statuses = [rig.client.post("/v1/work-items", json=WORK_ITEM_BODY).status_code for _ in range(61)]
        assert statuses[:60] == [201] * 60 and statuses[60] == 429, statuses
        assert len(stores.work_items.list(org, "owner", PRIYA)) == 60
    finally:
        clear()


# --- FS-15: a regression guard for issue #541 item 4a --------


def test_PPL_11c_FS_15_a_member_and_a_stranger_get_the_same_403_for_a_taken_and_a_free_address(people_rig):
    """The address check runs only once the actor is allowed to create people: a member (who may not) and a principal
    with no record at all learn nothing about which addresses the org holds (a mutant that ran `address_is_free`
    before the authorisation passes every other test)."""
    rig = people_rig()
    rig.add_people()
    rig.require_route(("POST", "/v1/people"))
    before = rig.snapshot()
    refusals = set()
    for user in (PRIYA, SAM, "u_stranger"):
        rig.as_user(user)
        for email in ("priya@example.com", "PRIYA@EXAMPLE.COM", "nobody.has.this@example.com"):
            response = rig.client.post("/v1/people", json=_body(email=email))
            assert response.status_code == 403, (user, email, response.status_code, response.text[:120])
            refusals.add(response.text)
    assert len(refusals) == 1, refusals
    assert rig.snapshot() == before
