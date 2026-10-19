"""CL-INT-5c (EFF-01, PRD 10.3, 10.4): a LOCAL DEV run goes from approve to a gate card and, once the owner approves
it, a FAKE send through the real outbox and policy engine. Nothing leaves the machine: the connector adapter only
records. The stand-ins exist only behind `dev.install`, are refused when deployed or live, and no request selects
them."""

from __future__ import annotations

import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tilo_api import deps, dev, dev_run, runs
from tilo_api.cards import build_router
from tilo_api.intake import router as intake_router
from tilo_api.side_effect_fields import Missing
from tilo_api.tasks import router as tasks_router


def _app() -> FastAPI:
    app = FastAPI()
    for router in (intake_router, tasks_router, build_router(runs.get_card_store, answer_guard=runs.answer_guard)):
        app.include_router(router)
    app.include_router(runs.router)
    return app


@pytest.fixture()
def dev_client(monkeypatch):
    for name in ("LIVE", "K_SERVICE", "CLOUD_RUN_JOB"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TILO_MODELS_FILE", str(dev.DEV_MODELS))
    app = _app()
    dev.install(app, {})
    return TestClient(app, base_url=f"http://localhost:{dev.PORT}")


def _wait(read, what: str, timeout: float = 15.0):
    deadline = time.monotonic() + timeout
    while not (value := read()):
        assert time.monotonic() < deadline, f"timed out waiting for {what}"
        time.sleep(0.05)
    return value


def _types(client: TestClient, world_id: str) -> list[str]:
    store = client.app.dependency_overrides[deps.get_store]()
    return [e["type"] for e in store.events.get(world_id, [])]


def _approve(client: TestClient) -> str:
    task = client.post("/intake", data={"text": "Prepare the weekly supplier summary."}).json()
    answers = [{"field": q["field"], "answer": None} for q in task["questions"]]
    client.post(f"/tasks/{task['task_id']}/answers", json={"answers": answers, "brief_edits": {}})
    approaches = client.get(f"/tasks/{task['task_id']}/approaches").json()
    body = {"approach_id": approaches["recommended"], "budget_cap": 50}
    response = client.post(f"/tasks/{task['task_id']}/approve", json=body)
    assert response.status_code == 200, response.text
    return response.json()["world_id"]


def test_CL_INT_5c_a_dev_run_reaches_a_gate_card_then_a_fake_send_through_the_outbox(dev_client):
    world_id = _approve(dev_client)

    cards = _wait(
        lambda: [c for c in dev_client.get(f"/worlds/{world_id}/cards").json() if c["kind"] == "gate"], "gate"
    )
    (card,) = cards
    adapters = dev_client.app.dependency_overrides[deps.get_connector_adapters]()
    assert "world.failed" not in _types(dev_client, world_id)
    assert all(a.sent == [] for a in adapters.values()), "nothing is sent before a person approves"
    assert card["gate"]["risk_tier"] == "T3"  # a recipient new to the owner: always a person (PRD 10.4)
    assert dev_run.DEV_RECIPIENT in card["gate"]["action"]["exact"]

    assert (
        dev_client.post(f"/worlds/{world_id}/cards/{card['id']}/answer", json={"option": "approve"}).status_code == 200
    )
    _wait(lambda: "world.completed" in _types(dev_client, world_id), "world.completed")

    types = _types(dev_client, world_id)
    assert "world.failed" not in types and types.count("data.transfer") == 1
    assert types.index("approval.requested") < types.index("approval.resolved") < types.index("data.transfer")
    (record,) = [r for a in adapters.values() for r in a.sent]  # the one fake send, recorded and sent nowhere
    assert record["recipients"] == [dev_run.DEV_RECIPIENT] and record["thread_id"] == dev_run.DEV_DESTINATION
    assert dev_client.get(f"/worlds/{world_id}/delivery").status_code == 200


def test_CL_INT_5c_a_send_that_is_not_approved_is_never_sent(dev_client):
    world_id = _approve(dev_client)
    cards = _wait(
        lambda: [c for c in dev_client.get(f"/worlds/{world_id}/cards").json() if c["kind"] == "gate"], "gate"
    )

    assert (
        dev_client.post(f"/worlds/{world_id}/cards/{cards[0]['id']}/answer", json={"option": "hold"}).status_code == 200
    )
    time.sleep(1.0)

    adapters = dev_client.app.dependency_overrides[deps.get_connector_adapters]()
    assert all(a.sent == [] for a in adapters.values())
    assert "data.transfer" not in _types(dev_client, world_id)


def test_CL_INT_5c_the_dev_seams_refuse_when_deployed_or_live(dev_client, monkeypatch):
    seams = dev_client.app.dependency_overrides
    for name, value in (("K_SERVICE", "tilo-api"), ("CLOUD_RUN_JOB", ""), ("LIVE", "1")):
        monkeypatch.setenv(name, value)
        with pytest.raises(dev.DevModeRefused):
            seams[deps.get_unit_runner]()
        with pytest.raises(dev.DevModeRefused):
            seams[deps.get_action_resolver]()
        with pytest.raises(dev.DevModeRefused):
            seams[deps.get_connector_adapters]()
        with pytest.raises(dev.DevModeRefused):
            dev_run.resolve_action(unit={}, action_type="send_email", item={}, brief={})
        monkeypatch.delenv(name)


def test_CL_INT_5c_the_production_seams_stay_unwired_and_no_request_input_selects_the_dev_ones(monkeypatch):
    for name in ("LIVE", "K_SERVICE", "CLOUD_RUN_JOB", "TILO_API_DEV"):
        monkeypatch.delenv(name, raising=False)
    app = _app()  # no dev.install: the defaults are the production wiring
    # Since ADR-0035 L6c (df7c7aa1) the production resolver is the real deterministic one (`side_effect_fields`), not an
    # unwired seam: with no answered recipient it still fails closed and never returns the dev's fixed fake recipient.
    with pytest.raises(Missing) as refused:
        deps.get_action_resolver()(unit={}, action_type="send_email", item={}, brief={})
    assert refused.value.fields == ("recipient",)
    assert deps.get_connector_adapters() == {}
    assert not any(seam in app.dependency_overrides for seam in (deps.get_action_resolver, deps.get_unit_runner))
    client = TestClient(app, raise_server_exceptions=False)
    selectors = {"dev": "1", "TILO_API_DEV": "1", "resolver": "dev"}
    response = client.post("/intake", data={"text": "Anything.", **selectors}, params=selectors, headers=selectors)
    assert response.status_code != 201
