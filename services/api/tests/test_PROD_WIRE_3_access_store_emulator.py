"""PROD-WIRE slice 3, part 3 (emulator): `tilo_api.prod.FirestoreAccessStore` against the real Firestore emulator (a
`demo-` project, no credentials; `tilo_harness.emulator.running_emulator`). `-m emulator` selects these. Each test uses
its own org id and uid, so the emulator's earlier documents never matter.

The unit half, with a fake client that also refuses `set`/`update`/`delete`, is `test_PROD_WIRE_3_access_store.py`.
"""

from __future__ import annotations

import uuid

import pytest
from _pw3_lib import DEMO, threads

pytestmark = pytest.mark.emulator


@pytest.fixture
def rig(pw3_emulator):
    """`rig()` -> `(prod, client, make_store, uid, org)`: the client comes from `prod.firestore_client` (the laptop
    guard: the emulator host and a demo- project), a fresh org and uid per test. Called inside the test, so a missing
    `tilo_api.prod` fails the test (an assertion), not its setup."""

    def open_rig():
        from _pw3_lib import import_prod

        prod = import_prod()
        client = prod.firestore_client(DEMO)
        org, uid = f"org_pw3_{uuid.uuid4().hex[:12]}", f"u_pw3_{uuid.uuid4().hex[:12]}"
        return prod, client, lambda: prod.FirestoreAccessStore(client, org_id=org), uid, org

    return open_rig


def test_PROD_WIRE_3_SEC_15_emulator_the_shared_client_is_a_real_client_on_the_emulator(rig):
    prod, client, _make, _uid, _org = rig()
    from google.cloud import firestore

    assert isinstance(client, firestore.Client) and client.project == DEMO
    assert prod.firestore_client(DEMO) is client, "one per process"


def test_PROD_WIRE_3_SEC_15_emulator_a_declaration_round_trips_at_orgs_org_access_uid(rig):
    _prod, client, make, uid, org = rig()
    store = make()
    assert store.get(uid) is None
    assert store.declare(uid, "judge") == "judge"
    assert store.get(uid) == "judge"
    assert make().get(uid) == "judge", "a new store object on the same Firestore sees it (it is stored, not cached)"
    assert client.document(f"orgs/{org}/access/{uid}").get().to_dict()["declaration"] == "judge"


def test_PROD_WIRE_3_SEC_15_emulator_a_second_different_declare_returns_the_first_and_changes_nothing(rig):
    _prod, client, make, uid, org = rig()
    store = make()
    assert store.declare(uid, "visitor") == "visitor"
    assert store.declare(uid, "judge") == "visitor"
    assert make().declare(uid, "judge") == "visitor", "another instance of the service, the same answer"
    assert store.get(uid) == "visitor"
    assert client.document(f"orgs/{org}/access/{uid}").get().to_dict()["declaration"] == "visitor"


def test_PROD_WIRE_3_SEC_15_emulator_eight_concurrent_first_declares_leave_exactly_one_stored(rig):
    _prod, client, make, uid, org = rig()
    values = ["judge", "visitor"] * 4
    stores = [make() for _ in values]  # eight store objects: eight instances racing on one document
    results = threads(8, lambda i: stores[i].declare(uid, values[i]))
    assert not [r for r in results if isinstance(r, BaseException)], results
    assert len(set(results)) == 1 and results[0] in {"judge", "visitor"}, f"all callers got one winner: {results}"
    stored = client.document(f"orgs/{org}/access/{uid}").get().to_dict()
    assert stored["declaration"] == results[0]
    assert make().get(uid) == results[0]


@pytest.mark.parametrize(
    "document",
    [{"declaration": "admin"}, {"declaration": 7}, {"declaration": None}, {"role": "judge"}],
    ids=["unknown-value", "wrong-type", "null", "missing-field"],
)
def test_PROD_WIRE_3_SEC_15_emulator_a_malformed_stored_document_reads_as_none(rig, document):
    _prod, client, make, uid, org = rig()
    client.document(f"orgs/{org}/access/{uid}").set(document)  # test setup only: a document someone wrote by hand
    assert make().get(uid) is None


def test_PROD_WIRE_3_SEC_15_emulator_a_uid_with_a_slash_or_empty_is_refused_before_the_emulator_is_asked(rig):
    _prod, client, make, _uid, org = rig()
    store = make()
    for uid in ("", "a/b"):
        with pytest.raises(ValueError):
            store.get(uid)
        with pytest.raises(ValueError):
            store.declare(uid, "judge")
    assert list(client.collection(f"orgs/{org}/access").stream()) == [], "nothing was written under the org"
