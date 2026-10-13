"""FR-MTR-10 / BQ-MTR10-4 (ticket T3, SEC-16): `deps.get_ledger` and `deps.get_ledger_writer`, once answering 503
whatever was deployed. Deployed (`K_SERVICE` or `CLOUD_RUN_JOB`) with a valid `TILO_FIRESTORE_PROJECT` they are the
Firestore Treasury ledger (`test_FR_MTR_10_T3_treasury_ledger_store.py`), the read narrowed to the signed-in person's
own entries. Pinned here, on `_adr35_l2_fake.OccFirestore`:

* deployed with a project, `GET /worlds/{id}/costs` and `GET /costs` are 200 with the recorded entries and no others;
* a ledger that cannot be built or read is 503, never an empty or invented report (HR-1), with the FS-18 back-off;
* owner-only is unchanged (a member 403, a stranger and an unknown world the same 404);
* a demo session writes nothing durable; off Cloud Run the seams stay 503 and dev mode's ledger takes the writes.
"""

from __future__ import annotations

from typing import Any

import pytest
from _adr35_l2_fake import OccFirestore
from _api_lib import make_world
from _t3_ledger_lib import ORG, OTHER, OWNER, ROOT, Flaky, entry, make
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

PROJECT = "tilo-dev-123456"


def _deployed(monkeypatch: pytest.MonkeyPatch, **env: str) -> None:
    from tilo_api import costs, deps, prod

    monkeypatch.setenv("K_SERVICE", "tilo-api")
    for name in ("FIRESTORE_EMULATOR_HOST", "GOOGLE_CLOUD_PROJECT", "CLOUD_RUN_JOB"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(deps, "_treasury_retry_at", None)
    prod.reset()
    costs.reset_credit_usd_cache()


def _wire(monkeypatch: pytest.MonkeyPatch, db: Any) -> None:
    from tilo_api import prod

    _deployed(monkeypatch, TILO_FIRESTORE_PROJECT=PROJECT)
    monkeypatch.setattr(prod, "build_client", lambda project: db)


def _app(*, user: str = OWNER, role: str = "owner", world_id: str | None = "w_x", demo: bool = False) -> TestClient:
    from tilo_api import deps
    from tilo_api.costs import router

    app = FastAPI()
    app.include_router(router)
    store = deps.Store()
    store.worlds["w_x"] = make_world(owner=OWNER, run_id="r_x")
    principal = deps.Principal(user_id=user, role=role, world_id=world_id, full_session=not demo, demo_session=demo)
    app.dependency_overrides[deps.get_current_principal] = lambda: principal
    app.dependency_overrides[deps.get_store] = lambda: store
    return TestClient(app)


def _request(app: FastAPI) -> Request:
    return Request({"type": "http", "app": app, "headers": [], "method": "GET", "path": "/", "query_string": b""})


# --- the routes over the deployed store ---


def test_FR_MTR_10_BQ_MTR10_4_deployed_with_a_project_costs_are_200_with_the_recorded_entries(monkeypatch):
    db = OccFirestore()
    ledger = make(db)
    ledger.append(entry(credits=4.0))
    ledger.append(entry(credits=6.0, step="s2"))
    ledger.append(entry(user=OTHER, credits=100.0))  # another person's spend on the same run id: not this report
    ledger.append(entry(run="r_elsewhere", credits=50.0))  # a run that is not this world's
    _wire(monkeypatch, db)
    client = _app()

    world = client.get("/worlds/w_x/costs")
    assert world.status_code == 200, world.text
    assert world.json()["totals"]["credits"] == pytest.approx(10.0)
    assert [t["run_id"] for t in world.json()["tasks"]] == ["r_x"]
    everything = client.get("/costs")
    assert everything.status_code == 200 and everything.json()["totals"]["credits"] == pytest.approx(10.0)
    assert {p.split("/")[2] for p in db.docs} == {"treasury_ledger"}, "one org-scoped collection"


def test_FR_MTR_10_BQ_MTR10_4_an_empty_but_readable_ledger_is_a_zero_report_not_a_refusal(monkeypatch):
    _wire(monkeypatch, OccFirestore())
    response = _app().get("/costs")
    assert response.status_code == 200 and response.json()["totals"]["credits"] == 0


def test_FR_MTR_10_BQ_MTR10_4_an_unreadable_ledger_is_503_with_no_numbers(monkeypatch):
    db = Flaky()
    make(db).append(entry())
    _wire(monkeypatch, db)
    client = _app()
    assert client.get("/costs").status_code == 200
    db.broken = True
    for path in ("/costs", "/worlds/w_x/costs"):
        response = client.get(path)
        assert response.status_code == 503, path
        assert "credits" not in response.text and "firestore" not in response.text.lower()


def test_FR_MTR_10_BQ_MTR10_4_one_unreadable_document_refuses_the_read_never_a_partial_report(monkeypatch):
    db = OccFirestore()
    make(db).append(entry())
    db.put(f"{ROOT}/hand_written", {"kind": "commit", "run": "r_x", "user": OWNER, "org": ORG, "credits": "a lot"})
    _wire(monkeypatch, db)
    response = _app().get("/costs")
    assert response.status_code == 503 and "credits" not in response.text


@pytest.mark.parametrize("project", [None, "", "Not A Project!", "a"])
def test_FR_MTR_10_BQ_MTR10_4_deployed_without_a_valid_project_both_seams_are_503(monkeypatch, project):
    _deployed(monkeypatch)
    monkeypatch.delenv("TILO_FIRESTORE_PROJECT", raising=False)
    if project is not None:
        monkeypatch.setenv("TILO_FIRESTORE_PROJECT", project)
    client = _app()
    response = client.get("/costs")
    assert response.status_code == 503 and response.json() == {"detail": "not_configured"}
    from tilo_api import deps

    assert deps.ledger_writer_for(_request(client.app)) is None


def test_FR_MTR_10_BQ_MTR10_4_a_client_that_cannot_be_built_is_503_and_backs_off(monkeypatch):
    from tilo_api import prod

    _deployed(monkeypatch, TILO_FIRESTORE_PROJECT=PROJECT)
    attempts: list[int] = []

    def boom(project: str) -> Any:
        attempts.append(1)
        raise OSError("no credentials")

    monkeypatch.setattr(prod, "build_client", boom)
    client = _app()
    for _ in range(3):
        assert client.get("/costs").status_code == 503
    assert len(attempts) == 1, "inside the FS-18 window no new build is tried"


def test_FR_MTR_10_BQ_MTR10_4_owner_only_is_unchanged_on_the_deployed_store(monkeypatch):
    db = OccFirestore()
    make(db).append(entry())
    _wire(monkeypatch, db)
    assert _app(user=OWNER, role="viewer").get("/worlds/w_x/costs").status_code == 403
    assert _app(user=OWNER, role="viewer").get("/costs").status_code == 403
    stranger = _app(user=OTHER, world_id="w_other").get("/worlds/w_x/costs")
    unknown = _app(user=OWNER, world_id="w_none").get("/worlds/w_none/costs")
    assert (stranger.status_code, unknown.status_code) == (404, 404) and stranger.content == unknown.content
    assert _app(user=OTHER, world_id=None).get("/costs").json()["totals"]["credits"] == 0, "no other person's rows"


# --- the writer seam -------------------------------------------------------------------------------------------


def test_FR_MTR_10_BQ_MTR10_4_deployed_the_writer_seam_is_the_same_store_and_a_demo_writes_nothing_durable(monkeypatch):
    from tilo_api import deps
    from tilo_api.treasury_firestore import FirestoreTreasuryLedger

    db = OccFirestore()
    _wire(monkeypatch, db)
    full = _request(_app().app)
    writer = deps.ledger_writer_for(full)
    assert isinstance(writer, FirestoreTreasuryLedger)
    writer.append(entry(credits=7.0))
    assert deps.get_ledger(full)[0].credits == 7.0 and len(db.docs) == 1

    demo = deps.ledger_writer_for(_request(_app(user="u_demo", demo=True).app))
    assert demo is not None and not isinstance(demo, FirestoreTreasuryLedger)
    demo.append(entry(user="u_demo"))
    assert len(db.docs) == 1, "an anonymous demo session stores nothing durable (BQ-DEMO-EPH-1)"


def test_FR_MTR_10_BQ_MTR10_4_off_cloud_run_the_seams_stay_503_and_dev_mode_uses_memory(monkeypatch):
    import test_CL_INT_5d_dev_run_pacing as pacing
    from fastapi import HTTPException
    from tilo_api import deps, dev

    for name in ("LIVE", "K_SERVICE", "CLOUD_RUN_JOB"):
        monkeypatch.delenv(name, raising=False)
    for seam in (deps.get_ledger, deps.get_ledger_writer):
        with pytest.raises(HTTPException) as caught:
            seam()
        assert caught.value.status_code == 503
    monkeypatch.setenv("TILO_MODELS_FILE", str(dev.DEV_MODELS))
    app = pacing._app()
    dev.install(app, {})
    writer = app.dependency_overrides[deps.get_ledger_writer]()
    writer.append(entry(user=dev.DEV_OWNER, credits=2.5))
    writer.append_once("unit_1", entry(user=dev.DEV_OWNER, credits=1.0))
    writer.append_once("unit_1", entry(user=dev.DEV_OWNER, credits=1.0))
    assert sorted(e.credits for e in app.dependency_overrides[deps.get_ledger]()) == [1.0, 2.5]
