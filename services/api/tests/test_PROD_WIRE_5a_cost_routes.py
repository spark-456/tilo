"""PROD-WIRE slice 5a (route level): `GET /worlds/{id}/costs` and `GET /costs` (FR-MTR-10) answer from the Firestore
ledger when the seams are wired (no `get_ledger` override). Setup reused from the FR-MTR-10 route tests
(`_mtr10_lib`: the same worlds, plans, events and Treasury ledger); the entries go into a fake Firestore client
(`_pw5_lib.LedgerClient`) through `FirestoreLedger.append`, and the config is a laptop's (the emulator host and a
`demo-` project, `TILO_API_STORE=firestore`) so the deployed access gate, which needs `K_SERVICE`, is not in play. The
expected body is the route's own answer when the same entries are served as a plain list.

Ambiguity resolved: the Treasury's entries carry the org `org_test`; they are stored with `org=org_tilo` (the only
org a Firestore ledger holds, ADR-0018 T4) so the test does not depend on whether the reader filters on the field.
"""

from __future__ import annotations

import math
from dataclasses import replace
from types import SimpleNamespace

import pytest
from _api_lib import as_principal, make_principal
from _mtr10_lib import A1, A2, OTHER, OWNER, RUN, B, build_ledger, seed
from _pw3_lib import DEMO, SENTINEL, Builder
from _pw5_lib import LedgerClient, firestore_ledger
from google.api_core import exceptions as gexc
from tilo_api import app, deps

PATHS = [f"/worlds/{A1}/costs", "/costs"]


@pytest.fixture()
def open_fsx(pw3, tmp_path):
    """`open_fsx()` stores the Treasury's ledger in a fake Firestore, wires the seams to it (no `get_ledger` override)
    and returns the rig. Called inside the test, so a missing `tilo_api.prod` fails the test, not its setup."""

    def open_rig():
        client = LedgerClient()
        builder = Builder(make=lambda: client)
        pw3.use(builder)
        pw3.laptop(DEMO, TILO_API_STORE="firestore")
        entries = [replace(e, org=deps.ORG_ID) for e in build_ledger(tmp_path).ledger]
        ledger = firestore_ledger()(client)
        for n, entry in enumerate(entries):
            ledger.append(entry, entry_id=f"e{n:04d}")
        assert deps.get_ledger not in app.dependency_overrides
        return SimpleNamespace(client=client, builder=builder, entries=entries, ledger=ledger)

    return open_rig


def _owner(world: str | None = A1):
    return make_principal(user_id=OWNER, role="owner", world_id=world)


def _bodies(client, fsx, path: str):
    """(from Firestore, from the same entries served as a list)."""
    from_firestore = client.get(path)
    app.dependency_overrides[deps.get_ledger] = lambda: tuple(fsx.entries)
    try:
        from_list = client.get(path)
    finally:
        del app.dependency_overrides[deps.get_ledger]
    return from_firestore, from_list


def test_PROD_WIRE_5a_FR_MTR_10_the_world_cost_comes_from_the_firestore_entries(client, store, open_fsx):
    fsx = open_fsx()
    seed(store)
    as_principal(_owner(A1))
    body, expected = _bodies(client, fsx, f"/worlds/{A1}/costs")
    assert body.status_code == 200, body.text
    assert body.json()["totals"]["credits"] == pytest.approx(200), "r_a1: 40 + 120 + 40, from the stored entries"
    assert math.isclose(body.json()["totals"]["usd"], 200 * 0.005)
    assert [t["run_id"] for t in body.json()["tasks"]] == [RUN[A1]]
    assert body.content == expected.content, "byte for byte what the list-backed route answers"
    assert fsx.builder.calls == [DEMO]


def test_PROD_WIRE_5a_FR_MTR_10_the_dashboard_sums_the_owners_worlds_from_firestore(client, store, open_fsx):
    fsx = open_fsx()
    seed(store)
    as_principal(_owner(None))
    body, expected = _bodies(client, fsx, "/costs")
    assert body.status_code == 200, body.text
    assert body.json()["totals"]["tasks"] == 2 and body.json()["totals"]["credits"] == pytest.approx(242)
    assert RUN[B] not in body.text, "the other owner's run is not in this owner's dashboard"
    assert body.content == expected.content


def test_PROD_WIRE_5a_FR_MTR_10_each_entry_is_counted_once_however_often_it_was_appended_and_reads_write_nothing(
    client, store, open_fsx
):
    fsx = open_fsx()
    seed(store)
    as_principal(_owner(A1))
    before = client.get(f"/worlds/{A1}/costs").content
    documents = len(fsx.client.ledger_docs())
    for n, entry in enumerate(fsx.entries):  # a retry of every write: the same ids, the same bodies
        fsx.ledger.append(entry, entry_id=f"e{n:04d}")
    assert len(fsx.client.ledger_docs()) == documents == len(fsx.entries)
    assert client.get(f"/worlds/{A1}/costs").content == before
    docs, ops = {p: dict(d) for p, d in fsx.client.docs.items()}, len(fsx.client.ops)
    for path in PATHS:  # and reading never writes
        assert client.get(path).status_code == 200
    assert fsx.client.docs == docs and fsx.client.writes() == []
    assert not [op for op, _ in fsx.client.ops[ops:] if op == "create"]


def test_PROD_WIRE_5a_ADR_0018_a_ledger_document_of_another_org_never_changes_the_cost(client, store, open_fsx):
    fsx = open_fsx()
    seed(store)
    as_principal(_owner(A1))
    before = client.get(f"/worlds/{A1}/costs")
    stray = firestore_ledger()(fsx.client, org_id="org_other")
    for n, entry in enumerate(fsx.entries):
        stray.append(replace(entry, credits=(entry.credits or 0) + 1000), entry_id=f"s{n:04d}")
    after = client.get(f"/worlds/{A1}/costs")
    assert after.status_code == 200 and after.content == before.content


def test_PROD_WIRE_5a_FR_MTR_10_the_access_rules_are_unchanged_on_the_firestore_ledger(client, store, open_fsx):
    open_fsx()
    seed(store)
    as_principal(make_principal(user_id="u_member", role="viewer", world_id=A1))
    for path in PATHS:
        refused = client.get(path)
        assert refused.status_code == 403 and "credits" not in refused.text, path
    as_principal(make_principal(user_id=OTHER, role="owner", world_id=B))
    assert client.get(f"/worlds/{A1}/costs").status_code == 404, "not a member: the unknown-world 404"
    as_principal(make_principal(user_id=OTHER, role="owner", world_id=A1))
    assert client.get(f"/worlds/{A1}/costs").status_code == 403, "another owner's id on this world"
    as_principal(make_principal(user_id=OTHER, role="owner", world_id=B))
    other = client.get(f"/worlds/{B}/costs")
    assert other.status_code == 200 and RUN[A1] not in other.text and RUN[A2] not in other.text


def test_PROD_WIRE_5a_FR_MTR_10_a_firestore_outage_is_a_503_that_names_no_error(client, store, open_fsx, caplog):
    fsx = open_fsx()
    seed(store)
    as_principal(_owner(A1))
    fsx.client.fail("stream", lambda: gexc.ServiceUnavailable(SENTINEL))
    for path in PATHS:
        response = client.get(path)
        assert response.status_code == 503, path
        assert SENTINEL not in response.text and SENTINEL not in caplog.text and "credits" not in response.text, path


def test_PROD_WIRE_5a_FR_MTR_10_unconfigured_the_routes_are_still_503_not_configured(client, store, pw3):
    seed(store)
    as_principal(_owner(A1))
    pw3.use(Builder(make=LedgerClient))  # nothing configured: no TILO_API_STORE
    for path in PATHS:
        response = client.get(path)
        assert response.status_code == 503 and response.json()["detail"] == "not_configured", path


def test_PROD_WIRE_5a_COST_FAST_1b_a_quick_charge_written_through_the_writer_shows_in_the_dashboard(
    client, store, open_fsx
):
    fsx = open_fsx()
    from tilo_api.quick_ledger import quick_entry

    seed(store)
    as_principal(_owner(None))
    before = client.get("/costs").json()["totals"]["credits"]
    at = fsx.entries[0].at  # any instant: Quick's pseudo run is the person's, not a world's
    deps.get_ledger_writer().append(quick_entry(OWNER, deps.ORG_ID, at, 7.0, "lite-31", (500, 200)))
    after = client.get("/costs").json()
    assert after["totals"]["credits"] == pytest.approx(before + 7.0)
    quick = [row for row in after["by_task_type"] if row["task_type"] == "quick_answer"]
    assert [(row["tasks"], row["credits"]) for row in quick] == [(1, 7.0)], (
        "labelled by task type, as for the list ledger"
    )
