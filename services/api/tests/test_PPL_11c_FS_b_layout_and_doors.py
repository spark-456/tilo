"""PPL-11c-FS FS-01 (the documents' layout, against the Firestore emulator) and FS-06 (the three doors into a
Firestore client, and "building the stores does no I/O"; no emulator needed). Spec: `API_PPL_11c_FS.md` sections 1
and 4.

`tilo_api.people_firestore` does not exist yet, so every test here fails with a missing module until the builder
writes it. No test here builds a real Firestore client: the doors are tried with a bomb in place of
`google.cloud.firestore.Client` and with a spy factory, and the layout tests use the emulator through `fs_backend`.
"""

from __future__ import annotations

import re
import subprocess
import sys
from unittest.mock import MagicMock

import pytest
from _ppl11c_fs_lib import (
    KINDS,
    STORE_OF,
    collections_of,
    edited,
    email_path,
    founder_path,
    make,
    person,
    raw,
    raw_ids,
    record_path,
    unique_org,
)
from tilo_people.stores import PeopleStores

emulator = pytest.mark.emulator

# --- FS-01: the layout ----------------------------------------------------------------------------------------------


@emulator
@pytest.mark.parametrize("kind", KINDS)
def test_PPL_11c_FS_01_a_record_is_one_document_at_orgs_org_people_kind_id_in_a_version_envelope(fs_backend, kind):
    """`orgs/{org}/people_{kind}/{id}` holds exactly `{"version": n, "record": <the record>}`: the version is the
    store's compare-and-set counter, never a field of the record (records are closed, so a client cannot forge it)."""
    org, client = unique_org(), fs_backend.client
    store = getattr(fs_backend.stores(), STORE_OF[kind])
    record = make(kind, 1, org)
    path = record_path(org, kind, record["id"])
    assert raw(client, path) is None
    store.create(record)
    doc = raw(client, path)
    assert doc == {"version": 1, "record": record}
    assert set(doc) == {"version", "record"} and type(doc["version"]) is int
    changed = edited(kind, record)
    store.replace(changed, expected_version=1)
    assert raw(client, path) == {"version": 2, "record": changed}
    store.delete(org, record["id"], expected_version=2)
    assert raw(client, path) is None, "a delete removes the document: no tombstone, no archive copy"


@emulator
def test_PPL_11c_FS_01_a_kind_is_its_own_collection_and_nothing_else_is_written(fs_backend):
    org, client = unique_org(), fs_backend.client
    stores = fs_backend.stores()
    stores.work_items.create(make("work_item", 1, org))
    stores.meetings.create(make("meeting", 1, org))
    assert collections_of(client, org) == {"people_work_item", "people_meeting"}
    assert raw_ids(client, f"orgs/{org}/people_work_item") == ["wi_w1"]
    assert {c.id for c in client.collections()} <= {"orgs"}, "everything lives under orgs/{org}"
    stores.pins.create(make("pinboard_item", 1, org))
    stores.mentions.create(make("mention", 1, org))
    stores.calendar.create(make("calendar_entry", 1, org))
    assert collections_of(client, org) == {
        "people_work_item",
        "people_meeting",
        "people_pinboard_item",
        "people_mention",
        "people_calendar_entry",
    }


@emulator
def test_PPL_11c_FS_01_a_person_create_writes_the_record_and_one_email_reservation_and_nothing_else(fs_backend):
    """The reservation lives in `orgs/{org}/people_directory/email_{sha256 hex of the lower-cased address}` and holds
    `{"person_id": id}`: the address itself is in the person record only, never in a path or another document."""
    org, client = unique_org(), fs_backend.client
    stores = fs_backend.stores()
    record = person("u_nina", org, email="Nina.Patel@Example.com")
    stores.persons.create(record)
    assert raw(client, record_path(org, "person", "u_nina")) == {"version": 1, "record": record}
    reservation = email_path(org, "nina.patel@example.com")
    assert reservation == email_path(org, "NINA.PATEL@EXAMPLE.COM"), "the key is of the lower-cased address"
    assert raw(client, reservation) == {"person_id": "u_nina"}
    directory = raw_ids(client, f"orgs/{org}/people_directory")
    assert directory == [reservation.rsplit("/", 1)[1]], directory
    assert re.fullmatch(r"email_[0-9a-f]{64}", directory[0])
    assert collections_of(client, org) == {"people_person", "people_directory"}
    for doc_id in directory:
        assert "nina" not in doc_id.lower() and "example" not in doc_id.lower()


@emulator
def test_PPL_11c_FS_01_the_founder_marker_is_orgs_org_people_directory_founder(fs_backend):
    org, client = unique_org(), fs_backend.client
    stores = fs_backend.stores()
    assert raw(client, founder_path(org)) is None
    stores.persons.create_founder(person("u_first", org, role="owner"))
    assert raw(client, founder_path(org)) == {"uid": "u_first"}
    assert raw(client, record_path(org, "person", "u_first"))["record"]["org_role"] == "owner"
    assert raw(client, email_path(org, "first@example.com")) == {"person_id": "u_first"}
    assert raw_ids(client, f"orgs/{org}/people_directory") == sorted(
        ["founder", email_path(org, "first@example.com").rsplit("/", 1)[1]]
    )
    other = unique_org()
    assert raw(client, founder_path(other)) is None, "the marker is per org"


@emulator
def test_PPL_11c_FS_01_a_founder_marker_outlives_the_person(fs_backend):
    org, client = unique_org(), fs_backend.client
    stores = fs_backend.stores()
    stores.persons.create_founder(person("u_first", org, role="owner"))
    stores.persons.create(person("u_second", org))
    stores.persons.delete(org, "u_first", expected_version=1)
    assert raw(client, record_path(org, "person", "u_first")) is None
    assert raw(client, email_path(org, "first@example.com")) is None, "the address is released"
    assert raw(client, founder_path(org)) == {"uid": "u_first"}, "the marker stays: nobody can re-found this org"


# --- FS-06: the doors -----------------------------------------------------------------------------------------------


def _bomb(monkeypatch):
    """`google.cloud.firestore.Client` replaced by one that records and refuses; returns the list of its calls."""
    calls: list[tuple] = []

    def refuse(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("a Firestore client was built")

    monkeypatch.setattr("google.cloud.firestore.Client", refuse)
    return calls


def _spy_client(monkeypatch):
    """`google.cloud.firestore.Client` replaced by one that returns one stub client; returns (calls, client)."""
    calls: list[tuple] = []
    client = MagicMock(name="firestore_client")

    def build(*args, **kwargs):
        calls.append((args, kwargs))
        return client

    monkeypatch.setattr("google.cloud.firestore.Client", build)
    return calls, client


def test_PPL_11c_FS_06_importing_the_module_builds_no_client():
    """A fresh interpreter imports the module with the Firestore client replaced by a bomb (no reload here: a reload
    would replace classes other tests hold)."""
    code = (
        "import google.cloud.firestore as f\n"
        "def bomb(*a, **k):\n"
        "    raise SystemExit('a Firestore client was built')\n"
        "f.Client = bomb\n"
        "import tilo_api.people_firestore as m\n"
        "names = ('firestore_people_stores', 'emulator_people_stores', 'open_people_stores',\n"
        "         'PeopleStoreNotConfigured')\n"
        "missing = [n for n in names if not hasattr(m, n)]\n"
        "print('missing ' + ','.join(missing) if missing else 'ok')\n"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120)
    assert done.stdout.strip() == "ok", (done.stdout, done.stderr[-500:])


def test_PPL_11c_FS_06_the_emulator_door_refuses_without_the_emulator_host(monkeypatch):
    """ADR-0003: emulator only, no cloud credentials. Same guard as `tilo_harness.store.FirestoreStore`."""
    from tilo_api.people_firestore import emulator_people_stores

    calls = _bomb(monkeypatch)
    monkeypatch.delenv("FIRESTORE_EMULATOR_HOST", raising=False)
    with pytest.raises(RuntimeError, match="FIRESTORE_EMULATOR_HOST"):
        emulator_people_stores()
    with pytest.raises(RuntimeError):
        emulator_people_stores("demo-unit")
    assert calls == [], "no client is built before the guard passes"


@pytest.mark.parametrize(
    "project",
    [
        "essential-wares-510320-f0",  # the real project: never through this door
        "tilo-dev",
        "tilo-demo",
        "demo_tilo",
        "Demo-tilo",
        "demo-",
        "demo-UPPER",
        "demo-tilo/x",
        "demo-tilo ",
        "demo-tilo\n",
        "",
        "demo",
    ],
)
def test_PPL_11c_FS_06_the_emulator_door_refuses_a_project_that_is_not_demo(monkeypatch, project):
    from tilo_api.people_firestore import emulator_people_stores

    calls = _bomb(monkeypatch)
    monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", "127.0.0.1:9")
    with pytest.raises(RuntimeError):
        emulator_people_stores(project)
    assert calls == []


def test_PPL_11c_FS_06_the_emulator_door_builds_the_stores_for_a_demo_project(monkeypatch):
    from tilo_api.people_firestore import emulator_people_stores

    calls, client = _spy_client(monkeypatch)
    monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", "127.0.0.1:9")
    stores = emulator_people_stores()  # the default project is demo-tilo, as the harness's FirestoreStore
    assert isinstance(stores, PeopleStores)
    assert len(calls) == 1 and "demo-tilo" in repr(calls[0])
    calls.clear()
    emulator_people_stores("demo-unit")
    assert len(calls) == 1 and "demo-unit" in repr(calls[0])
    assert client is not None


@pytest.mark.parametrize(
    "env",
    [
        {},
        {"TILO_PEOPLE_STORE": ""},
        {"TILO_PEOPLE_STORE": "memory"},
        {"TILO_PEOPLE_STORE": "Firestore"},
        {"TILO_PEOPLE_STORE": "firestore "},
        {"TILO_PEOPLE_STORE": "bigquery", "TILO_FIRESTORE_PROJECT": "tilo-test-project"},
        {"TILO_PEOPLE_STORE": "firestore"},
        {"TILO_PEOPLE_STORE": "firestore", "TILO_FIRESTORE_PROJECT": ""},
        {"TILO_PEOPLE_STORE": "firestore", "TILO_FIRESTORE_PROJECT": "X"},
        {"TILO_PEOPLE_STORE": "firestore", "TILO_FIRESTORE_PROJECT": "a b"},
        {"TILO_PEOPLE_STORE": "firestore", "TILO_FIRESTORE_PROJECT": "../x"},
        {"TILO_PEOPLE_STORE": "firestore", "TILO_FIRESTORE_PROJECT": "demo"},
        {"TILO_PEOPLE_STORE": "firestore", "TILO_FIRESTORE_PROJECT": "UPPER-case-project"},
        {"TILO_PEOPLE_STORE": "firestore", "TILO_FIRESTORE_PROJECT": "ends-with-dash-"},
        {"TILO_PEOPLE_STORE": "firestore", "TILO_FIRESTORE_PROJECT": "x" * 40},
        {"TILO_FIRESTORE_PROJECT": "tilo-test-project"},  # a project alone switches nothing on
        {
            "TILO_SCHEDULES_STORE": "firestore",
            "TILO_FIRESTORE_PROJECT": "tilo-test-project",
        },  # nor does the schedules switch
    ],
    ids=repr,
)
def test_PPL_11c_FS_06_the_config_door_refuses_anything_but_an_explicit_firestore_choice(monkeypatch, env):
    """ADR-0023 decision 2, for the people stores: the one live door is `TILO_PEOPLE_STORE=firestore` plus a valid
    `TILO_FIRESTORE_PROJECT`. Anything else raises `PeopleStoreNotConfigured` before any client exists."""
    from tilo_api.people_firestore import PeopleStoreNotConfigured, open_people_stores

    calls = _bomb(monkeypatch)
    made: list[str] = []

    def factory(project):
        made.append(project)
        raise AssertionError("a client factory was called")

    with pytest.raises(PeopleStoreNotConfigured) as caught:
        open_people_stores(env, client_factory=factory)
    assert calls == [] and made == []
    assert "TILO_PEOPLE_STORE" in str(caught.value), "the refusal says which switch to set"


def test_PPL_11c_FS_06_the_config_door_opens_for_an_explicit_firestore_choice(monkeypatch):
    from tilo_api.people_firestore import open_people_stores

    made: list[str] = []
    client = MagicMock(name="client")

    def factory(project):
        made.append(project)
        return client

    env = {"TILO_PEOPLE_STORE": "firestore", "TILO_FIRESTORE_PROJECT": "tilo-test-project"}
    stores = open_people_stores(env, client_factory=factory)
    assert isinstance(stores, PeopleStores) and made == ["tilo-test-project"]
    for name in STORE_OF.values():
        assert getattr(stores, name).kind in KINDS


def test_PPL_11c_FS_06_the_config_door_reads_the_process_environment_by_default(monkeypatch):
    from tilo_api.people_firestore import PeopleStoreNotConfigured, open_people_stores

    for name in ("TILO_PEOPLE_STORE", "TILO_FIRESTORE_PROJECT"):
        monkeypatch.delenv(name, raising=False)
    _bomb(monkeypatch)
    with pytest.raises(PeopleStoreNotConfigured):
        open_people_stores()
    calls, _client = _spy_client(monkeypatch)
    monkeypatch.setenv("TILO_PEOPLE_STORE", "firestore")
    # PROD-WIRE 3: the one guard (emulator + demo- project)
    monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", "127.0.0.1:9")
    monkeypatch.setenv("TILO_FIRESTORE_PROJECT", "demo-test-project")
    assert isinstance(open_people_stores(), PeopleStores)
    assert len(calls) == 1 and "demo-test-project" in repr(calls[0])


def test_PPL_11c_FS_06_building_the_stores_from_a_client_does_no_io():
    """`firestore_people_stores(client)` only holds the client: no read, write, query or transaction until a store
    method is called (so a deploy with a broken Firestore starts, and answers 503 per request instead of dying)."""
    from tilo_api.people_firestore import firestore_people_stores

    client = MagicMock(name="client")
    stores = firestore_people_stores(client)
    assert isinstance(stores, PeopleStores)
    names = {str(c[0]) for c in client.mock_calls}
    assert all(re.fullmatch(r"(collection|document)(\(\)\.(collection|document))*", n) for n in names), names
    kinds = {getattr(stores, name).kind for name in STORE_OF.values()}
    assert kinds == set(KINDS)
    assert len({id(getattr(stores, name)) for name in STORE_OF.values()}) == 6


def test_PPL_11c_FS_06_only_the_person_store_has_the_directory_calls():
    from tilo_api.people_firestore import firestore_people_stores

    for stores in (firestore_people_stores(MagicMock()), PeopleStores.in_memory()):
        assert callable(stores.persons.create_founder) and callable(stores.persons.founded)
        for name in STORE_OF.values():
            if name != "persons":
                assert not hasattr(getattr(stores, name), "create_founder")
                assert not hasattr(getattr(stores, name), "founded")


def test_PPL_11c_FS_06_the_people_package_stays_pure():
    """The adapter is tilo-api's: `tilo_people` imports no Firestore (its static-purity test forbids `google`), and
    the factory is not a `PeopleStores` classmethod for that reason (spec section 4)."""
    assert not hasattr(PeopleStores, "firestore")
