"""FR-MTR-10 / BQ-T3 / SEC-16 (ticket T3b, SEC-REVIEW-22 F2, F3, F4): the Treasury read cap and the silent shortfall.

Each entry is folded, in its transaction, into a per-run rollup the cost routes read (BQ-T3-5); `GET /costs` says
`partial` when its total can sit below the SEC-16 uid ledger (BQ-T3-6). Also: the `enforced()` guard, settle before
write, and read_<service> gates (FR-UX-18).
"""

from __future__ import annotations

import pytest
from _adr35_l2_fake import OccFirestore
from _api_lib import make_world
from _sec16_lib import JUDGE_A, make_ledger
from _t3_ledger_lib import ORG, OTHER, OWNER, Flaky, entry, make
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from test_FR_MTR_10_T3_live_metering_ledger import MINOR_PER_USD, ONE_UNIT, routed
from test_FR_MTR_10_T3_treasury_ledger_seams import PROJECT, _app, _deployed, _request, _wire
from test_SEC_16_api_spend_cap import BIG_LIMIT
from test_SEC_16_GOLIVE_935_metering import attempt

ROLLUP = f"orgs/{ORG}/treasury_rollup/"


def _spender_app(spend_ledger: object) -> TestClient:
    """`GET /costs` for JUDGE_A (world run `r_x`); `spend_ledger` is the SEC-16 ledger the route reads, or the error."""
    from tilo_api import deps
    from tilo_api.costs import router

    app, store = FastAPI(), deps.Store()
    app.include_router(router)
    store.worlds["w_x"] = make_world(owner=JUDGE_A, run_id="r_x")
    principal = deps.Principal(user_id=JUDGE_A, role="owner", world_id="w_x", full_session=True)
    app.dependency_overrides[deps.get_current_principal] = lambda: principal
    app.dependency_overrides[deps.get_store] = lambda: store

    def spend() -> object:
        if isinstance(spend_ledger, BaseException):
            raise spend_ledger
        return spend_ledger

    app.dependency_overrides[deps.get_spend_cap_ledger] = spend
    return TestClient(app)


# --- (1) the read cap is gone ------------------------------------------------------------------------------------


def test_FR_MTR_10_BQ_T3_more_than_5000_small_entries_is_still_a_200_with_the_right_total(monkeypatch):
    from tilo_api import deps
    from tilo_api.treasury_firestore import MAX_ENTRIES

    db = OccFirestore()
    ledger = make(db)
    for i in range(MAX_ENTRIES + 1):  # one paisa each: INR 50 of small settles
        ledger.append_once(f"unit_{i}", entry(credits=0.01, step="model"))
    _wire(monkeypatch, db)
    client = _app()
    total = (MAX_ENTRIES + 1) * 0.01

    assert [client.get(p).status_code for p in ("/costs", "/worlds/w_x/costs")] == [200, 200]
    assert client.get("/costs").json()["totals"]["credits"] == pytest.approx(total)
    assert client.get("/worlds/w_x/costs").json()["totals"]["credits"] == pytest.approx(total)
    seam = deps.get_ledger(_request(client.app))  # the one read /v1/effort makes as well
    assert 0 < len(seam) <= 2 and sum(e.credits for e in seam) == pytest.approx(total)
    assert len([p for p in db.docs if p.startswith(ROLLUP)]) == 1, "one rollup per person per run, not per entry"


def test_FR_MTR_10_BQ_T3_a_retried_settle_counts_once_in_the_rollup_and_in_one_transaction():
    db = OccFirestore()
    ledger = make(db)
    one = entry(credits=4.0)
    ledger.append_once("unit_a", one)
    ledger.append_once("unit_a", one)  # the retry: the entry exists, so the rollup is not touched again
    with pytest.raises(ValueError):
        ledger.append_once("unit_a", entry(credits=9.0))
    assert [e.credits for e in ledger.summary_for(OWNER)] == [4.0]
    assert sorted(p.split("/")[2] for p in db.committed_batches[0]) == ["treasury_ledger", "treasury_rollup"]
    assert len([b for b in db.committed_batches if b]) == 1, "the retry and the refused terms wrote nothing"


def test_FR_MTR_10_BQ_T3_entries_stay_the_audit_record_in_bounded_pages_of_own_rows():
    ledger = make(OccFirestore())
    for i in range(5):
        ledger.append_once(f"unit_{i}", entry(credits=float(i + 1)))
    ledger.append_once("unit_other", entry(user=OTHER, credits=50.0))
    first, cursor = ledger.entries_page(OWNER, limit=2)
    second, cursor = ledger.entries_page(OWNER, after=cursor, limit=2)
    last, end = ledger.entries_page(OWNER, after=cursor, limit=2)
    assert [len(first), len(second), len(last), end] == [2, 2, 1, None]
    assert sorted(e.credits for e in first + second + last) == [1.0, 2.0, 3.0, 4.0, 5.0]


def test_FR_MTR_10_BQ_T3_person_a_never_reads_person_b_and_unattributed_runs_fold_into_one():
    from tilo_api.spend_units import live_run_id

    db = OccFirestore()
    ledger = make(db)
    ledger.append_once("unit_a", entry(user=OWNER, credits=4.0))  # the same run id for both people
    ledger.append_once("unit_b", entry(user=OTHER, credits=50.0))
    for i, run in enumerate(("req_a", "task_b", "world_c")):
        ledger.append_once(f"unit_u{i}", entry(run=run, credits=1.0, step="model"))
    assert [(e.run, e.credits) for e in ledger.summary_for(OTHER)] == [("r_x", 50.0)]
    assert sorted((e.run, e.credits) for e in ledger.summary_for(OWNER)) == sorted(
        [("r_x", 4.0), (live_run_id(OWNER), 3.0)]
    )
    assert len([p for p in db.docs if p.startswith(ROLLUP)]) == 3


def test_FR_MTR_10_BQ_T3_an_unreadable_rollup_is_503_with_no_numbers_never_a_zero(monkeypatch):
    db = Flaky()
    make(db).append_once("unit_a", entry())
    _wire(monkeypatch, db)
    client = _app()
    assert client.get("/costs").status_code == 200
    bad = {"user": OWNER, "org": ORG, "run": "r_x", "credits": "lots", "entries": 1, "buckets": []}
    db.put(f"{ROLLUP}hand_written", bad)
    for path in ("/costs", "/worlds/w_x/costs"):
        response = client.get(path)
        assert response.status_code == 503 and "credits" not in response.text, path
    db.docs.pop(f"{ROLLUP}hand_written")
    db.broken = True
    assert client.get("/costs").status_code == 503


# --- (2) a shortfall is never silent ----------------------------------------------------------------------------


def test_FR_MTR_10_SEC_16_a_total_below_the_spend_ledger_is_marked_partial(monkeypatch):
    from tilo_api import costs

    spend, db = make_ledger(**BIG_LIMIT), Flaky()
    _wire(monkeypatch, db)
    writer, client = make(db), _spender_app(spend)
    call = {"attempts": [attempt(tokens_in=1_000, tokens_out=500)], "run": "r_x", "credit_usd": costs.credit_usd}

    routed(spend, writer, **call).generate("director", object())
    whole = client.get("/costs").json()
    one_unit = ONE_UNIT / MINOR_PER_USD / costs.credit_usd()  # what the cap ledger settled, as credits
    assert (whole["partial"], whole["partial_reason"]) == (False, None)
    assert whole["totals"]["credits"] == pytest.approx(one_unit)

    db.broken = True  # the next unit settles, then its ledger write fails: the Ledger now sits below the cap ledger
    routed(spend, writer, **call).generate("director", object())
    db.broken = False
    short = client.get("/costs").json()
    assert spend.settled_minor(JUDGE_A) == 2 * ONE_UNIT and short["totals"]["credits"] == pytest.approx(one_unit)
    assert (short["partial"], short["partial_reason"]) == (True, "below_spend_ledger")


def test_FR_MTR_10_SEC_16_a_spend_ledger_that_cannot_be_read_is_partial_not_complete(monkeypatch):
    _wire(monkeypatch, OccFirestore())
    body = _spender_app(HTTPException(status_code=503, detail="store_unavailable")).get("/costs").json()
    assert (body["partial"], body["partial_reason"]) == (True, "spend_ledger_unreadable")


# --- the guard, the order, and read gates ------------------------------------------------------------------------


def test_FR_MTR_10_BQ_T3_off_cloud_run_a_project_env_never_opens_the_store(monkeypatch):
    from tilo_api import deps, prod

    _deployed(monkeypatch)
    for name in ("K_SERVICE", "CLOUD_RUN_JOB"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TILO_FIRESTORE_PROJECT", PROJECT)  # a valid project, but not deployed
    built: list[str] = []
    monkeypatch.setattr(prod, "build_client", lambda project: built.append(project) or OccFirestore())
    for seam in (deps.get_ledger, deps.get_ledger_writer):
        with pytest.raises(HTTPException) as caught:
            seam()
        assert (caught.value.status_code, caught.value.detail) == (503, "not_configured")
    assert built == [], "the guard comes before any client is built"


def test_FR_MTR_10_SEC_16_the_cap_ledger_settles_before_the_treasury_write_is_made():
    spend, seen = make_ledger(**BIG_LIMIT), []

    class Watch:
        def append_once(self, entry_id: str, e: object) -> None:
            seen.append((spend.settled_minor(JUDGE_A), spend.spent_minor(JUDGE_A)))

    routed(spend, Watch(), attempts=[attempt(tokens_in=1_000, tokens_out=500)]).generate("director", object())
    assert seen == [(ONE_UNIT, ONE_UNIT)], "at the write the unit is already settled, not held"


@pytest.mark.parametrize("service", ["slack", "notion", "github", "stripe"])
def test_FR_UX_18_a_read_gate_for_a_connector_with_no_adapter_fails_the_unit_never_a_silent_no_op(service):
    """SEC-REVIEW-23: no field rule and no adapter, so the unit fails before any card or outbox entry."""
    import asyncio
    from types import SimpleNamespace

    from tilo_api import deps
    from tilo_api.runs import Run, _GateFailed

    action = f"read_{service}"
    run = object.__new__(Run)
    run.plan = {"gates": [{"id": "g1", "guards": ["u1"], "action_type": action, "risk_tier": "T3"}]}
    run.seams = SimpleNamespace(connectors=deps.get_connector_registry(), resolver=deps.get_action_resolver())
    run.adapters, run._supplied_for_unit, run.brief, run.person_answers = {}, {}, {}, {}
    unit = {"id": "u1", "district": "d", "connectors": [service]}

    assert deps.get_connector_adapters() == {}
    with pytest.raises(_GateFailed) as caught:
        asyncio.run(run.gate(unit, "worker", action, {"artifact_id": "a", "version": 1}, "made"))
    assert "no gate or connector" not in str(caught.value), "the gate and the connector are declared"
