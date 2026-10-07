"""PROD-WIRE slice 3, part 1: `tilo_api.prod.firestore_client(project)`, the one Firestore client per process per
project, and its guard (ADR-0026 decision 1; the same rules as `store_door.open_api_store`, now in one place so every
door obeys them). Helpers and the pinned interface: `_pw3_lib.py`. No test needs the emulator; no real client is built.

Ambiguities resolved (the brief's defaults, listed in the report):
- "K_SERVICE set" is presence (an empty string counts), as `access.enforced`; `store_door` tests truthiness.
- The guard runs on every call, before the cache is read: a process whose environment turns unsafe is refused even
  for a project it already holds a client for.
- An empty `FIRESTORE_EMULATOR_HOST` counts as unset (what `store_door` does); only non-empty values are tested.
"""

from __future__ import annotations

import logging

import pytest
from _pw3_lib import DEMO, EMULATOR, PROJECT, SENTINEL, Builder, threads
from tilo_api import store_door


def test_PROD_WIRE_3_the_module_pins_its_errors_and_its_seams(pw3):
    prod = pw3.use()
    from tilo_api.people_firestore import PeopleStoreNotConfigured

    assert callable(prod.firestore_client) and callable(prod.build_client) and callable(prod.reset)
    assert issubclass(prod.FirestoreNotConfigured, store_door.ApiStoreNotConfigured)
    assert issubclass(prod.FirestoreNotConfigured, PeopleStoreNotConfigured)  # both doors answer 503 not_configured
    assert issubclass(prod.FirestoreUnavailable, store_door.ApiStoreUnavailable)


def test_PROD_WIRE_3_one_client_per_project(pw3):
    builder = Builder()
    prod = pw3.use(builder)
    pw3.deployed(PROJECT)
    first = prod.firestore_client(PROJECT)
    assert prod.firestore_client(PROJECT) is first and prod.firestore_client(PROJECT) is first
    assert builder.calls == [PROJECT]
    assert first is builder.returned[0]


def test_PROD_WIRE_3_each_project_has_its_own_client(pw3, monkeypatch):
    builder = Builder()
    prod = pw3.use(builder)
    pw3.deployed(PROJECT)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT")  # not pinned, so a second project is a valid request
    other = "tilo-other-test"
    a, b = prod.firestore_client(PROJECT), prod.firestore_client(other)
    assert a is not b and builder.calls == [PROJECT, other]
    assert prod.firestore_client(other) is b and prod.firestore_client(PROJECT) is a
    assert builder.calls == [PROJECT, other]


def test_PROD_WIRE_3_concurrent_first_calls_build_exactly_one_client(pw3):
    builder = Builder(delay=0.05)
    prod = pw3.use(builder)
    pw3.deployed(PROJECT)
    results = threads(16, lambda i: prod.firestore_client(PROJECT))
    assert not [r for r in results if isinstance(r, BaseException)], results
    assert builder.calls == [PROJECT], "single-flight: N concurrent first calls, one build"
    assert all(r is builder.returned[0] for r in results)


def test_PROD_WIRE_3_the_default_builder_is_firestore_client_for_the_project(pw3):
    prod = pw3.use()  # the real default `build_client`; `google.cloud.firestore.Client` is the spy
    pw3.deployed(PROJECT)
    client = prod.firestore_client(PROJECT)
    assert client is pw3.real.made
    assert len(pw3.real.calls) == 1 and pw3.real.calls[0]["kwargs"].get("project") == PROJECT
    assert prod.firestore_client(PROJECT) is client and len(pw3.real.calls) == 1


@pytest.mark.parametrize(
    "project", ["", "Not A Project", "demo", "UPPER-case-1", "a" * 40, "1abcdef", "tilo-dev-test\n"]
)
def test_PROD_WIRE_3_a_bad_project_id_is_refused_before_any_client_is_built(pw3, project):
    builder = Builder()
    prod = pw3.use(builder)
    pw3.deployed(PROJECT)
    with pytest.raises(prod.FirestoreNotConfigured):
        prod.firestore_client(project)
    assert builder.calls == [] and pw3.real.calls == []


@pytest.mark.parametrize("k_service", ["tilo-api", ""], ids=["named", "empty-string"])
def test_PROD_WIRE_3_on_cloud_run_an_emulator_host_is_refused(pw3, k_service):
    builder = Builder()
    prod = pw3.use(builder)
    pw3.env(K_SERVICE=k_service, FIRESTORE_EMULATOR_HOST=EMULATOR)
    for project in (PROJECT, DEMO):
        with pytest.raises(prod.FirestoreNotConfigured):
            prod.firestore_client(project)
    assert builder.calls == []


@pytest.mark.parametrize("k_service", ["tilo-api", ""], ids=["named", "empty-string"])
def test_PROD_WIRE_3_on_cloud_run_a_live_project_opens_without_an_emulator(pw3, k_service):
    builder = Builder()
    prod = pw3.use(builder)
    pw3.env(K_SERVICE=k_service)  # presence, not truthiness: an empty value is still Cloud Run
    client = prod.firestore_client(PROJECT)
    assert client is builder.returned[0] and builder.calls == [PROJECT]


@pytest.mark.parametrize(
    ("project", "emulator"),
    [(DEMO, None), (PROJECT, None), (PROJECT, EMULATOR), ("demo", EMULATOR), ("demo-", EMULATOR)],
    ids=["demo-no-emulator", "live-no-emulator", "live-with-emulator", "too-short-id", "trailing-dash"],
)
def test_PROD_WIRE_3_a_laptop_opens_only_the_emulator_and_only_a_demo_project(pw3, project, emulator):
    builder = Builder()
    prod = pw3.use(builder)
    pw3.laptop(project, emulator=emulator)  # no K_SERVICE: a laptop that may hold real credentials
    with pytest.raises(prod.FirestoreNotConfigured):
        prod.firestore_client(project)
    assert builder.calls == [] and pw3.real.calls == []


def test_PROD_WIRE_3_a_laptop_with_the_emulator_and_a_demo_project_opens(pw3):
    builder = Builder()
    prod = pw3.use(builder)
    pw3.laptop(DEMO)
    assert prod.firestore_client(DEMO) is builder.returned[0] and builder.calls == [DEMO]


@pytest.mark.parametrize("where", ["cloud-run", "laptop"])
def test_PROD_WIRE_3_the_project_is_pinned_to_google_cloud_project(pw3, where):
    builder = Builder()
    prod = pw3.use(builder)
    project = PROJECT if where == "cloud-run" else DEMO
    if where == "cloud-run":
        pw3.env(K_SERVICE="tilo-api")
    else:
        pw3.laptop(project)
    pw3.env(GOOGLE_CLOUD_PROJECT="tilo-another-project")
    with pytest.raises(prod.FirestoreNotConfigured):
        prod.firestore_client(project)
    assert builder.calls == []
    pw3.env(GOOGLE_CLOUD_PROJECT=project)  # equal: fine
    assert prod.firestore_client(project) is builder.returned[0]


def test_PROD_WIRE_3_the_guard_is_read_from_the_environment_on_every_call(pw3):
    builder = Builder()
    prod = pw3.use(builder)
    pw3.env(K_SERVICE="tilo-api")
    held = prod.firestore_client(PROJECT)
    pw3.env(FIRESTORE_EMULATOR_HOST=EMULATOR)  # the environment turned unsafe: the held client is not handed out
    with pytest.raises(prod.FirestoreNotConfigured):
        prod.firestore_client(PROJECT)
    pw3.monkeypatch.delenv("FIRESTORE_EMULATOR_HOST")
    assert prod.firestore_client(PROJECT) is held and builder.calls == [PROJECT]


def test_PROD_WIRE_3_a_failed_build_is_not_cached_and_never_echoes_the_error(pw3, caplog):
    builder = Builder()
    builder.fail = True
    prod = pw3.use(builder)
    pw3.env(K_SERVICE="tilo-api")
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(prod.FirestoreUnavailable) as caught:
            prod.firestore_client(PROJECT)
    assert isinstance(caught.value, store_door.ApiStoreUnavailable)
    assert SENTINEL not in str(caught.value) and SENTINEL not in repr(caught.value)
    assert SENTINEL not in str(getattr(caught.value, "detail", ""))
    assert SENTINEL not in caplog.text, "nothing logs the exception text either"
    builder.fail = False  # the metadata server came back: the next call tries again
    client = prod.firestore_client(PROJECT)
    assert client is builder.returned[0] and builder.calls == [PROJECT, PROJECT]
    assert prod.firestore_client(PROJECT) is client and len(builder.calls) == 2


def test_PROD_WIRE_3_reset_forgets_every_cached_client(pw3):
    builder = Builder()
    prod = pw3.use(builder)
    pw3.env(K_SERVICE="tilo-api")
    first = prod.firestore_client(PROJECT)
    prod.reset()
    second = prod.firestore_client(PROJECT)
    assert second is not first and builder.calls == [PROJECT, PROJECT]
