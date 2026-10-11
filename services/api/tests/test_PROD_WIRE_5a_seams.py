"""PROD-WIRE slice 5a (unit): the deployed seams `deps.get_ledger` (FR-MTR-10, BQ-MTR10-4) and `deps.get_ledger_writer`
(COST-FAST-1b, BQ-COSTFAST-7) on a `prod.FirestoreLedger` over the process's one shared Firestore client, under the same
rule as `deps.get_access_store` (PROD-WIRE 3): `TILO_API_STORE=firestore` and the api door opens through
`prod.firestore_client`; otherwise 503 `not_configured`, never cached; a failing client build is a 503 that never
echoes the error. Dev mode's overrides are untouched. Helpers: `_pw3_lib.py` (rig, builder), `_pw5_lib.py` (client).

Ambiguity resolved: the FS-18 back-off window after a failed build (`deps.PEOPLE_STORES_BACKOFF_S`) is pinned for the
access door in PW3, not here; these tests do not retry inside a window.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from _pw3_lib import AMBIENT, DEMO, PROJECT, SENTINEL, Builder
from _pw5_lib import AT, LedgerClient, firestore_ledger, make_entry
from fastapi import HTTPException
from tilo_api import deps
from tilo_metering import LedgerEntry

SEAMS = ("get_ledger", "get_ledger_writer")


@pytest.fixture(autouse=True)
def _no_leaked_access_backoff(monkeypatch):
    monkeypatch.setattr(deps, "_door_retry_at", None)  # a failed build elsewhere must not leak into these tests


def _wired(pw3, client=None):
    client = client if client is not None else LedgerClient()
    builder = Builder(make=lambda: client)
    pw3.use(builder)
    pw3.deployed(PROJECT, api=True)
    return client, builder


def test_PROD_WIRE_5a_FR_MTR_10_get_ledger_reads_the_firestore_entries_of_org_tilo_afresh_on_every_call(pw3):
    client, _ = _wired(pw3)
    a, b = make_entry(run="r_a"), make_entry(run="r_b", at=AT + timedelta(minutes=1))
    firestore_ledger()(client).append(b, entry_id="id_b")
    firestore_ledger()(client).append(a, entry_id="id_a")
    got = deps.get_ledger()
    assert list(got) == [a, b] and all(isinstance(e, LedgerEntry) for e in got)
    firestore_ledger()(client).append(make_entry(run="r_c", at=AT + timedelta(minutes=2)), entry_id="id_c")
    assert [e.run for e in deps.get_ledger()] == ["r_a", "r_b", "r_c"], "a later entry is seen at once"
    firestore_ledger()(client, org_id="org_other").append(make_entry(run="r_theirs"), entry_id="id_x")
    assert [e.run for e in deps.get_ledger()] == ["r_a", "r_b", "r_c"], "ADR-0018 T4: org_tilo only"
    assert deps.ORG_ID == "org_tilo"


def test_PROD_WIRE_5a_COST_FAST_1b_get_ledger_writer_append_is_append_entry_and_a_retry_adds_nothing(pw3):
    from tilo_api.quick_ledger import quick_entry

    client, _ = _wired(pw3)
    entry = make_entry(run="r_quick_x", step="quick")
    assert deps.get_ledger_writer().append(entry) is None
    deps.get_ledger_writer().append(entry)  # the writer is fetched again, as a second request would
    assert list(deps.get_ledger()) == [entry] and len(client.ledger_docs()) == 1 and client.writes() == []
    via_ledger = LedgerClient()
    firestore_ledger()(via_ledger).append_entry(entry)
    assert client.ledger_docs() == via_ledger.ledger_docs(), "the same id and the same body as append_entry"
    quick = quick_entry("u_pw5_owner", deps.ORG_ID, AT, 3.25, "flash-38", (1200, 340))  # what Quick intake appends
    deps.get_ledger_writer().append(quick)
    assert quick in list(deps.get_ledger()), "usage, step and run survive the round trip"


def test_PROD_WIRE_5a_without_the_api_store_switch_the_ledger_seams_are_503_not_configured_and_never_cached(pw3):
    configs = {
        "no-config": {},
        "memory": {"TILO_API_STORE": "memory"},
        "bad-project": {"TILO_API_STORE": "firestore", "TILO_FIRESTORE_PROJECT": "Not A Project"},
        "people-switch-only": {"TILO_PEOPLE_STORE": "firestore"},
    }
    builder = Builder(make=LedgerClient)
    pw3.use(builder)
    for name, config in configs.items():
        for ambient in AMBIENT:  # a clean environment for each configuration
            pw3.monkeypatch.delenv(ambient, raising=False)
        pw3.deployed(PROJECT, **{k: v for k, v in config.items() if k == "TILO_PEOPLE_STORE"})
        for key, value in config.items():
            pw3.env(**{key: value})
        for seam in SEAMS:
            for _ in range(2):
                with pytest.raises(HTTPException) as refused:
                    getattr(deps, seam)()
                assert (refused.value.status_code, refused.value.detail) == (503, "not_configured"), f"{name}/{seam}"
        assert builder.calls == [], f"{name}: no client was built"
    pw3.env(TILO_API_STORE="firestore", TILO_FIRESTORE_PROJECT=PROJECT)  # configured later: no stale refusal
    for seam in SEAMS:
        assert getattr(deps, seam)() is not None
    assert builder.calls == [PROJECT]


def test_PROD_WIRE_5a_outside_cloud_run_only_the_emulator_and_a_demo_project_open_the_ledger_seams(pw3):
    builder = Builder(make=LedgerClient)
    pw3.use(builder)
    pw3.laptop(PROJECT, TILO_API_STORE="firestore")  # a real project id on a laptop, even with an emulator host
    for seam in SEAMS:
        with pytest.raises(HTTPException) as refused:
            getattr(deps, seam)()
        assert (refused.value.status_code, refused.value.detail) == (503, "not_configured"), seam
    assert builder.calls == []
    pw3.laptop(DEMO, TILO_API_STORE="firestore")
    assert list(deps.get_ledger()) == [] and builder.calls == [DEMO]


def test_PROD_WIRE_5a_a_failing_client_build_is_a_503_that_never_echoes_the_error(pw3, caplog):
    builder = Builder(make=LedgerClient)
    builder.fail = True
    pw3.use(builder)
    pw3.deployed(PROJECT, api=True)
    for seam in SEAMS:
        with pytest.raises(HTTPException) as refused:
            getattr(deps, seam)()
        assert refused.value.status_code == 503, seam
        assert SENTINEL not in str(refused.value.detail) and "cannot reach" not in str(refused.value.detail), seam
        if seam == SEAMS[0]:  # the build was attempted: a configured door that fails is not "not configured"
            assert builder.calls == [PROJECT] and refused.value.detail == "store_unavailable"
    assert SENTINEL not in caplog.text


def test_PROD_WIRE_5a_the_ledger_seams_use_the_one_shared_client_of_the_process(pw3):
    client, builder = _wired(pw3)
    deps.get_ledger_writer().append(make_entry())
    list(deps.get_ledger())
    deps.get_access_store().get("u_pw5_owner")
    assert builder.calls == [PROJECT], "one client built for the project; the ledger asked prod.firestore_client for it"
    assert len(client.ledger_docs()) == 1


def test_PROD_WIRE_5a_dev_mode_overrides_keep_answering_from_the_dev_ledger_and_build_no_client(pw3, monkeypatch):
    from fastapi.testclient import TestClient
    from test_CL_INT_5d_dev_run_pacing import _app
    from tilo_api import dev
    from tilo_api.costs import router as costs_router

    builder = Builder(make=LedgerClient)
    pw3.use(builder)
    pw3.laptop(DEMO, TILO_API_STORE="firestore")  # a Firestore config does not displace dev mode
    monkeypatch.setenv("TILO_MODELS_FILE", str(dev.DEV_MODELS))
    app = _app()
    app.include_router(costs_router)
    dev.install(app, {})
    override = app.dependency_overrides[deps.get_ledger]
    assert getattr(override, "__self__", None).__class__ is dev.DevLedger, "dev's own ledger, not the Firestore one"
    assert list(override()) == []
    client = TestClient(app, base_url=f"http://localhost:{dev.PORT}")
    assert client.get("/costs").status_code == 200
    assert builder.calls == [], "dev mode never builds a Firestore client"
