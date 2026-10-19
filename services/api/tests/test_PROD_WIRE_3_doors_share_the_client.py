"""PROD-WIRE slice 3, part 2: the api store door (`durable_store.deployed`) and the people stores door
(`deps.get_people_stores`) take their Firestore client from `tilo_api.prod.firestore_client`, so one process holds one
client per project and both doors obey one guard. Helpers: `_pw3_lib.py`. No emulator, no real client.
"""

from __future__ import annotations

import pytest
from _pw3_lib import DEMO, EMULATOR, PROJECT, SENTINEL, Builder
from fastapi import HTTPException
from tilo_api import deps, durable_store, store_door


def _refused(call) -> HTTPException:
    with pytest.raises(HTTPException) as caught:
        call()
    return caught.value


def _is_503(exc: HTTPException, detail: str) -> bool:
    return exc.status_code == 503 and exc.detail == detail


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.mark.parametrize("first", ["api", "people"])
def test_PROD_WIRE_3_both_doors_use_one_client_built_once(pw3, first):
    builder = Builder()
    pw3.use(builder)
    pw3.deployed(PROJECT, api=True, people=True)
    order = [("api", lambda: durable_store.deployed()), ("people", lambda: deps.get_people_stores())]
    order.sort(key=lambda item: item[0] != first)
    opened = {name: call() for name, call in order}
    assert builder.calls == [PROJECT], "one Firestore client for the whole process"
    client = builder.returned[0]
    store, writer = opened["api"]
    assert store.backend.client is client, "the api store's records backend runs on the shared client"
    assert opened["people"].persons._client is client, "the people stores run on the same client"
    assert durable_store.deployed()[0] is store and deps.get_people_stores() is opened["people"]
    assert builder.calls == [PROJECT] and pw3.real.calls == [] and writer is store.writer


def test_PROD_WIRE_3_the_default_factories_of_both_doors_delegate_to_the_shared_client(pw3):
    from tilo_api.people_firestore import open_people_stores

    builder = Builder()
    prod = pw3.use(builder)
    pw3.deployed(PROJECT)
    client = store_door.client_factory(PROJECT)
    assert client is prod.firestore_client(PROJECT) is builder.returned[0]
    env = {"TILO_PEOPLE_STORE": "firestore", "TILO_FIRESTORE_PROJECT": PROJECT}
    assert open_people_stores(env).persons._client is client
    assert builder.calls == [PROJECT] and pw3.real.calls == []


@pytest.mark.parametrize(
    "config",
    [
        {"K_SERVICE": "tilo-api", "FIRESTORE_EMULATOR_HOST": EMULATOR},
        {"K_SERVICE": "tilo-api", "GOOGLE_CLOUD_PROJECT": "tilo-another-project"},
    ],
    ids=["cloud-run-with-an-emulator-host", "cloud-run-project-mismatch"],
)
def test_PROD_WIRE_3_a_refused_environment_builds_no_client_for_either_door(pw3, config):
    builder = Builder()
    pw3.use(builder)
    pw3.env(TILO_API_STORE="firestore", TILO_PEOPLE_STORE="firestore", TILO_FIRESTORE_PROJECT=PROJECT, **config)
    for call in (durable_store.deployed, deps.get_people_stores):
        for _ in range(2):  # a refusal is never cached
            assert _is_503(_refused(call), "not_configured")
    assert builder.calls == [] and pw3.real.calls == []


@pytest.mark.parametrize("emulator", [None, EMULATOR], ids=["no-emulator", "emulator-but-a-live-project"])
def test_PROD_WIRE_3_the_people_door_inherits_the_laptop_guard(pw3, emulator):
    builder = Builder()
    pw3.use(builder)
    pw3.laptop(PROJECT, emulator=emulator, TILO_PEOPLE_STORE="firestore")  # no K_SERVICE, and not a demo- project
    for _ in range(2):
        assert _is_503(_refused(deps.get_people_stores), "not_configured")
    assert builder.calls == [] and pw3.real.calls == [], "no client, not the real one either"


def test_PROD_WIRE_3_a_people_refusal_is_not_backed_off_and_the_door_opens_once_the_environment_is_right(pw3):
    builder, clock = Builder(), FakeClock()
    pw3.use(builder)
    pw3.monkeypatch.setattr(deps, "people_stores_clock", clock, raising=False)
    pw3.laptop(PROJECT, emulator=None, TILO_PEOPLE_STORE="firestore")
    assert _is_503(_refused(deps.get_people_stores), "not_configured")
    pw3.deployed(PROJECT, people=True)  # the same process, now on Cloud Run: no clock advance, no cache_clear
    stores = deps.get_people_stores()
    assert stores.persons._client is builder.returned[0] and builder.calls == [PROJECT]


def test_PROD_WIRE_3_the_people_door_still_opens_on_the_emulator_with_a_demo_project(pw3):
    builder = Builder()
    pw3.use(builder)
    pw3.laptop(DEMO, TILO_PEOPLE_STORE="firestore")
    stores = deps.get_people_stores()
    assert stores.persons._client is builder.returned[0] and builder.calls == [DEMO]


@pytest.mark.parametrize(
    "config", [{}, {"TILO_API_STORE": "memory", "TILO_PEOPLE_STORE": "memory"}], ids=["unset", "memory"]
)
def test_PROD_WIRE_3_k_service_alone_opens_nothing(pw3, config):
    builder = Builder()
    pw3.use(builder)
    pw3.deployed(PROJECT, **config)  # Cloud Run, a project, and no switch for any store
    for call in (deps.get_store, deps.get_people_stores, deps.get_event_writer):
        for _ in range(2):
            assert _is_503(_refused(call), "not_configured")
    assert builder.calls == [] and pw3.real.calls == []


def test_PROD_WIRE_3_a_failing_build_is_503_on_each_door_never_echoed_and_retried(pw3):
    builder, clock = Builder(), FakeClock()
    builder.fail = True
    pw3.use(builder)
    pw3.monkeypatch.setattr(deps, "people_stores_clock", clock, raising=False)
    pw3.deployed(PROJECT, api=True, people=True)
    api_error = _refused(durable_store.deployed)
    assert _is_503(api_error, "store_unavailable") and SENTINEL not in str(api_error.detail)
    people_error = _refused(deps.get_people_stores)
    assert _is_503(people_error, "not_configured") and SENTINEL not in str(people_error.detail)
    assert builder.calls == [PROJECT, PROJECT], "a failed build is not cached by the shared root"
    builder.fail = False
    store, _writer = durable_store.deployed()  # the api door tries again at once
    assert store.backend.client is builder.returned[0] and builder.calls == [PROJECT] * 3
    assert _is_503(_refused(deps.get_people_stores), "not_configured")  # FS-18: still inside its own backoff
    assert builder.calls == [PROJECT] * 3
    clock.now += deps.PEOPLE_STORES_BACKOFF_S + 1
    assert deps.get_people_stores().persons._client is store.backend.client and builder.calls == [PROJECT] * 3
