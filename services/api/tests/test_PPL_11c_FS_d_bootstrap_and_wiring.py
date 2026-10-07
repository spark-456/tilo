"""PPL-11c-FS FS-12 (the founder is bound to a configured bootstrap uid, issue #541 item 1) and FS-13 (how
`deps.get_people_stores` is wired: one set of stores per process, built only on explicit configuration, 503
otherwise; issue #549 item 1). Spec: `API_PPL_11c_FS.md` sections 4 and 5. None needs the emulator.

The PPL-11a `Rig` lets every principal found an empty org (its `get_founder_gate` override says yes, as the PPL-11c S3
tests assume); the FS-12 tests `unwire("founder_gate")` to get the production gate, which reads
`TILO_PEOPLE_BOOTSTRAP_UID` on every call. A refused `/v1/people/first` is always the same 403 `forbidden`, whatever
the reason (not the bootstrap uid, the org already has a person, the org was founded before).
"""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

import pytest
from _ppl11a_lib import OWNER, run_threads
from _ppl11c_fs_lib import SENTINEL, errs, oks, race
from _ppl11c_lib import PERSON_BODY, R_PERSON_FIRST, assert_unwired_is_503
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient
from tilo_people.stores import PeopleStores, erase_person

ENV_UID = "TILO_PEOPLE_BOOTSTRAP_UID"
ENV_STORE = "TILO_PEOPLE_STORE"
ENV_PROJECT = "TILO_FIRESTORE_PROJECT"
FOUNDER = "u_founder"
FORBIDDEN = {"detail": "forbidden"}


def _body(**changes):
    return {**PERSON_BODY, **changes}


def _clear_env(monkeypatch):
    for name in (ENV_UID, ENV_STORE, ENV_PROJECT, "K_SERVICE", "CLOUD_RUN_JOB", "TILO_API_DEV"):
        monkeypatch.delenv(name, raising=False)


def _first(rig, body=None):
    rig.require_route(R_PERSON_FIRST)
    return rig.client.post("/v1/people/first", json=_body() if body is None else body)


def _prod_gate_rig(people_rig, monkeypatch, *, configured: str | None = None):
    """A rig whose `/first` runs the production gate; signed in as u_founder."""
    _clear_env(monkeypatch)
    rig = people_rig()
    rig.unwire("founder_gate")
    if configured is not None:
        monkeypatch.setenv(ENV_UID, configured)
    rig.as_user(FOUNDER)
    return rig


# --- FS-12: the bootstrap uid --------


def test_PPL_11c_FS_12_with_no_bootstrap_uid_configured_nobody_founds_an_empty_org(people_rig, monkeypatch):
    """BQ default (docs/open-questions.md BQ-PPL11C-15): unconfigured is closed. A declared visitor or judge cannot
    claim an empty org (issue #541 item 1)."""
    rig = _prod_gate_rig(people_rig, monkeypatch)
    before = rig.snapshot()
    for user in (FOUNDER, "u_dev_owner", "u_anyone", OWNER):
        rig.as_user(user)
        refused = _first(rig)
        assert refused.status_code == 403 and refused.json() == FORBIDDEN, (user, refused.status_code, refused.text)
    assert rig.snapshot() == before and rig.stored("persons", FOUNDER) is None
    assert rig.store_calls == [], "the gate is checked before any store is read or written"


def test_PPL_11c_FS_12_the_configured_uid_founds_the_org_as_its_owner(people_rig, monkeypatch):
    rig = _prod_gate_rig(people_rig, monkeypatch, configured=FOUNDER)
    created = _first(rig)
    assert created.status_code == 201, created.text[:300]
    assert created.json() == {"id": FOUNDER, "display_name": "Nina Patel", "org_role": "owner", "memberships": []}
    stored = rig.stored("persons", FOUNDER)
    assert (stored["id"], stored["org_id"], stored["org_role"]) == (FOUNDER, rig.org, "owner")
    assert rig.real.persons.founded(rig.org) is True, "`/first` writes the founder marker with the person"
    assert _first(rig).status_code == 403, "once"


def test_PPL_11c_FS_12_any_other_principal_is_refused_with_the_same_403(people_rig, monkeypatch):
    rig = _prod_gate_rig(people_rig, monkeypatch, configured=FOUNDER)
    rig.as_user("u_other")
    before = rig.snapshot()
    wrong_uid = _first(rig)
    assert wrong_uid.status_code == 403 and wrong_uid.json() == FORBIDDEN
    assert rig.snapshot() == before and rig.store_calls == []
    rig.as_user(FOUNDER)
    assert _first(rig).status_code == 201
    rig.as_user("u_other")
    already_founded = _first(rig)  # the uid is wrong AND the org is founded: still the same body
    rig.as_user(FOUNDER)
    founder_again = _first(rig)  # the right uid, the org is founded
    assert {wrong_uid.text, already_founded.text, founder_again.text} == {wrong_uid.text}, (
        "one refusal for every reason"
    )
    assert {r.status_code for r in (wrong_uid, already_founded, founder_again)} == {403}


def test_PPL_11c_FS_12_the_gate_runs_before_the_body_is_checked_against_the_schema(people_rig, monkeypatch):
    """A body the closed request model accepts but the person schema refuses (a lower-case zone): the bootstrap uid
    learns it is a 422, anyone else only ever sees the 403 (no oracle on an empty org)."""
    rig = _prod_gate_rig(people_rig, monkeypatch, configured=FOUNDER)
    bad = _body(time_zone="nowhere")
    rig.as_user("u_other")
    refused = _first(rig, bad)
    assert refused.status_code == 403 and refused.json() == FORBIDDEN
    assert rig.store_calls == []
    rig.as_user(FOUNDER)
    assert _first(rig, bad).status_code == 422
    assert rig.stored("persons", FOUNDER) is None


@pytest.mark.parametrize("principal", ["U_FOUNDER", "u_Founder", "u_founder2", "u_founde", "u_founder_"])
def test_PPL_11c_FS_12_the_match_is_exact(people_rig, monkeypatch, principal):
    rig = _prod_gate_rig(people_rig, monkeypatch, configured=FOUNDER)
    rig.as_user(principal)
    refused = _first(rig)
    assert refused.status_code == 403 and refused.json() == FORBIDDEN, principal
    assert rig.stored("persons", principal) is None


@pytest.mark.parametrize(
    "configured",
    [
        "",
        " u_founder",
        "u_founder ",
        "u_founder\n",
        "founder",
        "u_",
        "u_" + "x" * 60,
        "*",
        "u_a,u_founder",
        "u_founder;u_x",
    ],
    ids=repr,
)
def test_PPL_11c_FS_12_a_value_that_is_not_a_user_id_configures_nothing(people_rig, monkeypatch, configured):
    """The value must be a `common#user_id` as it stands (no trimming, no list, no wildcard): anything else is the
    unconfigured default, so a typo in the deploy closes the door instead of opening it."""
    rig = _prod_gate_rig(people_rig, monkeypatch, configured=configured)
    refused = _first(rig)
    assert refused.status_code == 403 and refused.json() == FORBIDDEN, repr(configured)
    assert rig.stored("persons", FOUNDER) is None


def test_PPL_11c_FS_12_the_variable_is_read_on_every_request(people_rig, monkeypatch):
    rig = _prod_gate_rig(people_rig, monkeypatch, configured="u_someone_else")
    assert _first(rig).status_code == 403
    monkeypatch.setenv(ENV_UID, FOUNDER)
    assert _first(rig).status_code == 201, "no per-process cache of the setting"


def test_PPL_11c_FS_12_the_seam_is_a_predicate_over_the_configured_uid(monkeypatch):
    from tilo_api import deps

    _clear_env(monkeypatch)
    assert deps.get_founder_gate()(FOUNDER) is False and deps.get_founder_gate()("") is False
    monkeypatch.setenv(ENV_UID, FOUNDER)
    gate = deps.get_founder_gate()
    assert gate(FOUNDER) is True
    for other in ("u_other", "U_FOUNDER", "", " u_founder", "u_founder "):
        assert gate(other) is False, repr(other)


def test_PPL_11c_FS_12_an_org_that_already_has_people_is_refused_to_the_bootstrap_uid_too(people_rig, monkeypatch):
    rig = _prod_gate_rig(people_rig, monkeypatch, configured=FOUNDER)
    rig.add_people()
    before = rig.snapshot()
    refused = _first(rig)
    assert refused.status_code == 403 and refused.json() == FORBIDDEN
    assert rig.snapshot() == before


def test_PPL_11c_FS_12_an_erased_org_cannot_be_refounded_not_even_by_the_bootstrap_uid(people_rig, monkeypatch):
    """The founder marker stays after the founder is erased (issue #541 item 2): no stranger, and not even the
    configured uid, can mint a new owner for the old team's pins once the org has emptied."""
    rig = _prod_gate_rig(people_rig, monkeypatch, configured=FOUNDER)
    assert _first(rig).status_code == 201
    rig.require_route(("POST", "/v1/people"))
    second = rig.post("/v1/people", _body(email="second@example.com", display_name="Second"))
    assert second.status_code == 201
    assert erase_person(rig.real, rig.org, FOUNDER)["person"] == 1
    assert erase_person(rig.real, rig.org, second.json()["id"])["person"] == 1  # the org is founded: allowed
    assert rig.real.persons.list(rig.org) == ()
    refused = _first(rig, _body(email="again@example.com"))
    assert refused.status_code == 403 and refused.json() == FORBIDDEN
    assert rig.real.persons.list(rig.org) == ()


def test_PPL_11c_FS_12_the_configured_uid_has_no_other_power(people_rig, monkeypatch):
    """Bootstrap is for founding one empty org, not a role: with an org in place, the configured uid with no person
    record is a stranger like any other (it cannot add people)."""
    rig = _prod_gate_rig(people_rig, monkeypatch, configured=FOUNDER)
    rig.add_people()
    rig.as_user(FOUNDER)
    before = rig.snapshot()
    refused = rig.post("/v1/people", _body(email="x@example.com"))
    assert refused.status_code == 403
    assert rig.snapshot() == before


def test_PPL_11c_FS_12_eight_principals_racing_one_bootstrap_uid_leave_its_owner(people_rig, monkeypatch):
    rig = _prod_gate_rig(people_rig, monkeypatch, configured="u_f3")
    rig.require_route(R_PERSON_FIRST)

    def principal(request: Request):
        return rig.deps.Principal(user_id=request.headers["x-test-user"], role="owner")

    rig.app.dependency_overrides[rig.deps.get_current_principal] = principal

    def claim(i: int) -> int:
        with TestClient(rig.app, raise_server_exceptions=False) as client:
            body = _body(email=f"founder{i}@example.com", display_name=f"Founder {i}")
            return client.post("/v1/people/first", json=body, headers={"x-test-user": f"u_f{i}"}).status_code

    statuses = run_threads(8, claim)
    assert sorted(statuses) == [201] + [403] * 7, statuses
    assert [s.record["id"] for s in rig.real.persons.list(rig.org)] == ["u_f3"]


# --- FS-13: how the process gets its people stores --------


@pytest.fixture
def fresh_stores_cache(monkeypatch):
    """No setting from the environment, and the process-wide stores of `deps.get_people_stores` forgotten before and
    after the test."""
    from tilo_api import deps

    _clear_env(monkeypatch)

    def forget():
        clear = getattr(deps.get_people_stores, "cache_clear", None)
        if clear is not None:
            clear()

    forget()
    yield deps
    forget()


def _bomb_client(monkeypatch):
    calls: list[tuple] = []

    def refuse(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("a Firestore client was built")

    monkeypatch.setattr("google.cloud.firestore.Client", refuse)
    return calls


def _expect_503(deps):
    with pytest.raises(HTTPException) as caught:
        deps.get_people_stores()
    assert caught.value.status_code == 503 and caught.value.detail == "not_configured"


@pytest.mark.parametrize("deployed", [False, True], ids=["local", "deployed"])
@pytest.mark.parametrize(
    "env",
    [
        {},
        {ENV_STORE: ""},
        {ENV_STORE: "memory"},
        {ENV_STORE: "FIRESTORE"},
        {ENV_STORE: "firestore"},
        {ENV_STORE: "firestore", ENV_PROJECT: "X"},
        {ENV_STORE: "firestore", ENV_PROJECT: "../x"},
        {ENV_PROJECT: "tilo-test-project"},
        {"TILO_SCHEDULES_STORE": "firestore", ENV_PROJECT: "tilo-test-project"},
    ],
    ids=repr,
)
def test_PPL_11c_FS_13_the_default_is_503_and_builds_no_client(fresh_stores_cache, monkeypatch, env, deployed):
    """Production fails closed (ADR-0023 decision 3): no switch, a wrong switch, or a switch without a valid project
    is 503 `not_configured` and no Firestore client is ever built; nothing falls back to memory."""
    deps = fresh_stores_cache
    calls = _bomb_client(monkeypatch)
    if deployed:
        monkeypatch.setenv("K_SERVICE", "tilo-api")
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    _expect_503(deps)
    _expect_503(deps)  # a refusal is not cached either
    assert calls == []


def test_PPL_11c_FS_13_the_default_is_503_and_builds_no_client_on_every_people_route(people_rig, monkeypatch):
    from _ppl11a_lib import R_CREATE_PERSON, R_PLATE
    from _ppl11c_lib import R_MT_GET, R_WI_LIST

    _clear_env(monkeypatch)
    assert_unwired_is_503(people_rig, [R_PERSON_FIRST, R_CREATE_PERSON, R_WI_LIST, R_MT_GET, R_PLATE], "people_stores")


def _spy_client(monkeypatch, *, delay: float = 0.0):
    calls: list[tuple] = []
    client = MagicMock(name="firestore_client")
    lock = threading.Lock()

    def build(*args, **kwargs):
        if delay:
            time.sleep(delay)
        with lock:
            calls.append((args, kwargs))
        return client

    monkeypatch.setattr("google.cloud.firestore.Client", build)
    return calls, client


def test_PPL_11c_FS_13_an_explicit_config_builds_the_firestore_stores_once_per_process(fresh_stores_cache, monkeypatch):
    deps = fresh_stores_cache
    calls, _client = _spy_client(monkeypatch)
    monkeypatch.setenv(ENV_STORE, "firestore")
    monkeypatch.setenv(ENV_PROJECT, "tilo-test-project")
    first = deps.get_people_stores()
    assert isinstance(first, PeopleStores)
    assert deps.get_people_stores() is first, "one PeopleStores per process: the limiter and the keys live on it"
    assert len(calls) == 1 and "tilo-test-project" in repr(calls[0])
    monkeypatch.setenv(ENV_STORE, "")  # the object is the process's: a later change of the setting is not re-read
    assert deps.get_people_stores() is first


def test_PPL_11c_FS_13_eight_first_requests_build_one_set_of_stores(fresh_stores_cache, monkeypatch):
    """`functools.cache` alone lets two threads that arrive together each build one (two limiters, two clients): the
    first build is single-flight."""
    deps = fresh_stores_cache
    calls, _client = _spy_client(monkeypatch, delay=0.05)
    monkeypatch.setenv(ENV_STORE, "firestore")
    monkeypatch.setenv(ENV_PROJECT, "tilo-test-project")
    results = race([lambda: deps.get_people_stores() for _ in range(8)])
    assert not errs(results), errs(results)
    assert len(calls) == 1, f"{len(calls)} clients were built"
    assert len({id(g) for g in oks(results)}) == 1


def test_PPL_11c_FS_13_a_failed_build_is_a_503_that_is_not_cached_and_leaks_nothing(
    fresh_stores_cache, monkeypatch, caplog
):
    deps = fresh_stores_cache
    state = {"fail": True}
    client = MagicMock(name="firestore_client")

    def build(*args, **kwargs):
        if state["fail"]:
            raise RuntimeError(f"cannot reach {SENTINEL}")
        return client

    monkeypatch.setattr("google.cloud.firestore.Client", build)
    monkeypatch.setenv(ENV_STORE, "firestore")
    monkeypatch.setenv(ENV_PROJECT, "tilo-test-project")
    with pytest.raises(HTTPException) as caught:
        deps.get_people_stores()
    assert caught.value.status_code == 503 and caught.value.detail == "not_configured"
    assert SENTINEL not in repr(caught.value) and SENTINEL not in caplog.text
    state["fail"] = False
    assert isinstance(deps.get_people_stores(), PeopleStores), "the next request tries again"


def test_PPL_11c_FS_13_the_default_is_503_and_builds_no_client_on_import():
    """A fresh interpreter imports `tilo_api.deps` and `tilo_api` with the Firestore client replaced by a bomb."""
    import subprocess
    import sys

    code = "\n".join(
        [
            "import google.cloud.firestore as f",
            "def bomb(*a, **k):",
            "    raise SystemExit('a Firestore client was built')",
            "f.Client = bomb",
            "import tilo_api, tilo_api.deps",
            "print('ok')",
        ]
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0 and done.stdout.strip() == "ok", done.stderr[-500:]
