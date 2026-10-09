"""PROD-WIRE slice 5a (emulator): `tilo_api.prod.FirestoreLedger` against the real Firestore emulator (a `demo-`
project, no credentials; `tilo_harness.emulator.running_emulator`). `-m emulator` selects these. Each ledger test
uses its own org id, so the emulator's earlier documents never matter; the deployed end-to-end test uses the real org
(`org_tilo`, the only one the seams read) with ids no other test uses.

The unit half, with a fake client that also refuses `set`/`update`/`delete`, is `test_PROD_WIRE_5a_firestore_ledger.py`.
"""

from __future__ import annotations

import random
import uuid
from datetime import timedelta

import pytest
from _pw3_lib import DEMO, import_prod, threads
from _pw5_lib import AT, doc_path, make_entry
from tilo_api import deps

pytestmark = pytest.mark.emulator

CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


@pytest.fixture
def rig(pw3_emulator):
    """`rig()` -> `(prod, client, make_ledger, org)`: the client comes from `prod.firestore_client` (the laptop guard),
    a fresh org per test. Called inside the test, so a missing module fails the test (an assertion), not its setup."""

    def open_rig():
        prod = import_prod()
        client = prod.firestore_client(DEMO)
        org = f"org_pw5_{uuid.uuid4().hex[:12]}"
        return prod, client, lambda: prod.FirestoreLedger(client, org_id=org), org

    return open_rig


def test_PROD_WIRE_5a_emulator_an_entry_round_trips_exactly_at_orgs_org_ledger_id(rig):
    prod, client, make, org = rig()
    ledger = make()
    assert list(ledger.entries()) == []
    entries = [make_entry(run=f"r_{n}", at=AT + timedelta(minutes=n), credits=n + 0.5) for n in (3, 1, 2)]
    for n, entry in zip((3, 1, 2), entries, strict=True):
        ledger.append(entry, entry_id=f"id_{n}")
    assert list(make().entries()) == sorted(entries, key=lambda e: e.at), "stored, not cached; sorted by (at, id)"
    stored = client.document(doc_path("id_1", org)).get().to_dict()
    assert isinstance(stored["at"], str) and stored["day"] == "2026-06-01"
    assert stored["usage"] == {"profile": "flash-38", "tokens_in": 1000, "tokens_out": 500}


def test_PROD_WIRE_5a_emulator_an_identical_append_is_a_no_op_and_a_different_body_is_a_conflict(rig):
    prod, client, make, org = rig()
    ledger, entry = make(), make_entry()
    ledger.append(entry, entry_id="same")
    assert ledger.append(entry, entry_id="same") is None
    assert make().append(entry, entry_id="same") is None, "another instance of the service, the same answer"
    with pytest.raises(prod.LedgerConflict):
        ledger.append(make_entry(credits=99.0), entry_id="same")
    assert list(ledger.entries()) == [entry]
    assert client.document(doc_path("same", org)).get().to_dict()["credits"] == 12.5
    quick = make_entry(step="quick", run="r_quick_pw5")  # append_entry: a deterministic id, so a retry adds nothing
    for _ in range(3):
        make().append_entry(quick)
    assert len(list(client.collection(f"orgs/{org}/ledger").stream())) == 2
    assert quick in list(make().entries())


def test_PROD_WIRE_5a_emulator_eight_concurrent_appends_of_one_id_leave_exactly_one_document(rig):
    _prod, client, make, org = rig()
    ledgers = [make() for _ in range(8)]  # eight instances of the service racing on one document
    entry = make_entry()
    results = threads(8, lambda i: ledgers[i].append(entry, entry_id="race"))
    assert results == [None] * 8, results
    assert len(list(client.collection(f"orgs/{org}/ledger").stream())) == 1
    assert list(make().entries()) == [entry]


def test_PROD_WIRE_5a_emulator_eight_concurrent_appends_of_one_id_and_different_bodies_leave_one_winner(rig):
    prod, client, make, org = rig()
    ledgers = [make() for _ in range(8)]
    entries = [make_entry(credits=float(i + 1)) for i in range(8)]
    results = threads(8, lambda i: ledgers[i].append(entries[i], entry_id="race"))
    assert sum(r is None for r in results) == 1, results
    assert all(isinstance(r, prod.LedgerConflict) for r in results if r is not None), results
    [stored] = list(make().entries())
    assert stored in entries
    assert len(list(client.collection(f"orgs/{org}/ledger").stream())) == 1


def test_PROD_WIRE_5a_emulator_a_document_of_another_org_is_never_read(rig):
    prod, client, make, org = rig()
    mine = make_entry(run="r_mine")
    make().append(mine, entry_id="a")
    other = prod.FirestoreLedger(client, org_id=f"{org}_other")
    other.append(make_entry(run="r_theirs", credits=999.0), entry_id="b")
    assert list(make().entries()) == [mine]
    assert [e.run for e in other.entries()] == ["r_theirs"]


def test_PROD_WIRE_5a_emulator_deployed_a_cost_event_reaches_the_ledger_the_seams_read(pw3_emulator):
    from tilo_api import durable_store

    pw3_emulator.setenv("TILO_API_STORE", "firestore")
    pw3_emulator.setenv("TILO_FIRESTORE_PROJECT", DEMO)
    world, run = f"w_pw5_{uuid.uuid4().hex[:12]}", f"r_pw5_{uuid.uuid4().hex[:12]}"
    event_id = "01JB5VQ" + "".join(random.choices(CROCKFORD, k=19))  # noqa: S311 - a unique id, not security
    owner = "u_pw5_deployed_owner"
    store, _writer = durable_store.deployed()
    store.commit(worlds={world: deps.WorldRecord(owner=owner, districts={}, run_id=run)}, create=[("worlds", world)])
    part = {
        "id": event_id, "type": "agent.idle", "actor": "A_director", "target": "A_director", "level": None,
        "district": None, "item": None, "severity": "info", "credits": 2.5, "cause": None, "vis": "all",
        "authz": None, "summary": "The Director is waiting.", "data": {},
    }  # fmt: skip
    writer = deps.get_event_writer()
    committed = writer.append(world, part)

    mine = [e for e in deps.get_ledger() if e.run == run]
    assert len(mine) == 1 and (mine[0].kind, mine[0].user, mine[0].credits, mine[0].org) == (
        "commit", owner, 2.5, "org_tilo",
    )  # fmt: skip
    assert mine[0].at.isoformat().startswith(committed["ts"][:19])
    from tilo_api import prod

    stored = prod.firestore_client(DEMO).document(doc_path(event_id)).get()
    assert stored.exists, "orgs/org_tilo/ledger/{event id}"

    writer.append(world, part)  # an idempotent resend
    assert [e for e in deps.get_ledger() if e.run == run] == mine, "appends nothing new"

    quick_run = f"r_quick_{uuid.uuid4().hex[:12]}"
    quick = make_entry(run=quick_run, user=owner, step="quick")
    deps.get_ledger_writer().append(quick)
    deps.get_ledger_writer().append(quick)
    assert [e for e in deps.get_ledger() if e.run == quick_run] == [quick]
