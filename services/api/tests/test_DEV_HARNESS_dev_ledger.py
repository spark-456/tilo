"""DEV-HARNESS (c): the cost routes answer in dev mode. `dev.install` wires ONE ledger through the same seam production
will use (`deps.get_ledger`): an in-memory ledger fed by the dev run's own recorded cost events (priced from
config/prices.dev.yaml, no paid call), so `/worlds/{id}/costs` and `/costs` can be compared with the credits the UI
reads off the events. Owner-only semantics are unchanged and a process that is not in dev mode still answers 503."""

from __future__ import annotations

import math

import pytest
from _api_lib import make_world
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_CL_INT_5d_dev_run_pacing import _app, _approve, _finish
from tilo_api import deps, dev
from tilo_api.costs import router as costs_router
from tilo_metering import LedgerEntry


@pytest.fixture()
def dev_client(monkeypatch):
    for name in ("LIVE", "K_SERVICE", "CLOUD_RUN_JOB"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TILO_MODELS_FILE", str(dev.DEV_MODELS))
    app = _app()
    app.include_router(costs_router)
    dev.install(app, {})
    return TestClient(app, base_url=f"http://localhost:{dev.PORT}")


def _ledger(client: TestClient) -> list[LedgerEntry]:
    return list(client.app.dependency_overrides[deps.get_ledger]())


def test_DEV_HARNESS_c_after_a_dev_run_the_world_costs_equal_the_ledger_sum(dev_client):
    world_id, _ = _approve(dev_client, cap=8)
    stream = _finish(dev_client, world_id)
    event_credits = math.fsum(e["credits"] for e in stream)
    assert event_credits > 0

    entries = _ledger(dev_client)
    assert entries and {e.kind for e in entries} == {"commit"}
    assert math.fsum(e.credits or 0 for e in entries) == pytest.approx(event_credits)
    assert {e.user for e in entries} == {dev.DEV_OWNER} and {e.run for e in entries} == {stream[0]["run_id"]}

    response = dev_client.get(f"/worlds/{world_id}/costs")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["world_id"] == world_id
    assert body["totals"]["credits"] == pytest.approx(event_credits)
    assert body["totals"]["credits"] == pytest.approx(math.fsum(e.credits or 0 for e in entries))
    assert [p["profile"] for p in body["by_profile"]] == ["dev-unit"]
    assert body["totals"]["usd"] == pytest.approx(event_credits * 0.005)


def test_DEV_HARNESS_c_the_dashboard_sums_the_owners_worlds(dev_client):
    first, _ = _approve(dev_client, cap=8)
    second, _ = _approve(dev_client, cap=8)
    total = math.fsum(e["credits"] for w in (first, second) for e in _finish(dev_client, w))

    body = dev_client.get("/costs").json()
    assert (
        body["totals"]["credits"]
        == pytest.approx(total)
        == pytest.approx(math.fsum(e.credits or 0 for e in _ledger(dev_client)))
    )
    assert body["totals"]["tasks"] == 2


def test_DEV_HARNESS_c_a_replayed_event_is_not_counted_twice(dev_client):
    world_id, _ = _approve(dev_client, cap=8)
    stream = _finish(dev_client, world_id)
    writer = dev_client.app.dependency_overrides[deps.get_event_writer]()
    charged = next(e for e in stream if e["credits"])
    before = len(_ledger(dev_client))
    assert writer.append(world_id, dict(charged)) == charged  # idempotent by id: nothing new committed
    assert len(_ledger(dev_client)) == before


def test_DEV_HARNESS_c_owner_only_semantics_are_unchanged(dev_client):
    world_id, _ = _approve(dev_client, cap=8)
    _finish(dev_client, world_id)
    store = dev_client.app.dependency_overrides[deps.get_store]()
    store.worlds["w_other"] = make_world(owner="u_someone_else")  # a world the dev owner does not own
    assert dev_client.get("/worlds/w_unknown/costs").status_code == 404
    refused = dev_client.get("/worlds/w_other/costs")
    assert refused.status_code == 403 and "totals" not in refused.text
    assert "w_other" not in dev_client.get("/costs").text  # the dashboard is the signed-in owner's worlds only


def test_DEV_HARNESS_c_nothing_else_reaches_the_ledger(dev_client):
    assert _ledger(dev_client) == []
    world_id, _ = _approve(dev_client, cap=8)
    assert dev_client.get(f"/worlds/{world_id}/costs").status_code == 200  # reading never writes
    assert math.fsum(e.credits or 0 for e in _ledger(dev_client)) <= 8


def test_DEV_HARNESS_c_production_without_dev_mode_still_answers_503(monkeypatch):
    for name in ("TILO_API_DEV", "K_SERVICE", "CLOUD_RUN_JOB", "LIVE"):
        monkeypatch.delenv(name, raising=False)
    app = FastAPI()
    app.include_router(costs_router)
    app.dependency_overrides[deps.get_current_principal] = lambda: deps.Principal(
        user_id="u_owner", role="owner", world_id="w_x", full_session=True
    )
    app.dependency_overrides[deps.get_store] = lambda: deps.Store()
    client = TestClient(app)
    for path in ("/costs", "/worlds/w_x/costs"):
        response = client.get(path)
        assert response.status_code == 503 and response.json()["detail"] == "not_configured", path
    assert deps.get_ledger not in app.dependency_overrides
    with pytest.raises(Exception, match="503|not_configured"):
        deps.get_ledger()


def test_DEV_HARNESS_c_the_dev_ledger_refuses_when_deployed(dev_client, monkeypatch):
    monkeypatch.setenv("K_SERVICE", "tilo-api")
    with pytest.raises(dev.DevModeRefused):
        dev_client.app.dependency_overrides[deps.get_ledger]()
