"""DEV-HARNESS (d): a routine can be fired end to end in dev mode without a Google ID token. `POST /dev/schedules/tick`
exists ONLY after `dev.install` (TILO_API_DEV=1, loopback Host only); it runs the tick's own fan-out and delivery
(`schedules._fan_out`, `schedules._run_task`, the code `POST /internal/schedules/tick` runs after its token check) with
an in-process Tasks client. The real route and its OIDC check are untouched, the L3 `grant_budget` policy a scheduled
run needs is still required, and nothing makes a paid call."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from _fr_agt_14_lib import l3_budget_policy
from fastapi.testclient import TestClient
from test_CL_INT_5d_dev_run_pacing import _app, _events, _wait
from tilo_api import app as production_app
from tilo_api import deps, dev, schedules

CADENCE = {"weekday": 0, "hour": 9, "minute": 0, "tz": "Asia/Kolkata"}
PATH = "/dev/schedules/tick"


@pytest.fixture()
def dev_client(monkeypatch):
    for name in ("LIVE", "K_SERVICE", "CLOUD_RUN_JOB", "TILO_SCHEDULES_STORE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TILO_API_DEV", "1")  # the schedule store defaults to memory only in dev mode
    monkeypatch.setenv("TILO_MODELS_FILE", str(dev.DEV_MODELS))
    schedules.get_schedule_store.cache_clear()
    app = _app()
    app.include_router(schedules.router)
    dev.install(app, {})
    yield TestClient(app, base_url=f"http://localhost:{dev.PORT}")
    schedules.get_schedule_store.cache_clear()


def _schedule(client: TestClient) -> dict:
    task = client.post("/intake", data={"text": "Prepare the weekly supplier summary."}).json()
    answers = [{"field": q["field"], "answer": None} for q in task["questions"]]
    client.post(f"/tasks/{task['task_id']}/answers", json={"answers": answers, "brief_edits": {}})
    recommended = client.get(f"/tasks/{task['task_id']}/approaches").json()["recommended"]
    approved = client.post(f"/tasks/{task['task_id']}/approve", json={"approach_id": recommended, "budget_cap": 8})
    assert approved.status_code == 200, approved.text
    created = client.post(
        "/schedules",
        json={"task_id": task["task_id"], "approach_id": recommended, "title": "Weekly summary", "cadence": CADENCE},
    )
    assert created.status_code == 201, created.text
    return created.json()


def _as_of(schedule: dict) -> str:
    due = datetime.fromisoformat(schedule["next_due"].replace("Z", "+00:00"))
    return (due + timedelta(minutes=1)).astimezone(UTC).isoformat()


def _grant_policy(client: TestClient) -> None:
    client.app.dependency_overrides[deps.get_store]().policies["pol_auto_budget"] = l3_budget_policy(dev.DEV_OWNER)


def test_DEV_HARNESS_d_a_due_routine_runs_end_to_end_to_its_gate_card(dev_client):
    schedule = _schedule(dev_client)
    _grant_policy(dev_client)

    response = dev_client.post(PATH, json={"as_of": _as_of(schedule)})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["fired"] == 1 and [t["ran"] for t in body["tasks"]] == [1]
    world_id = dev_client.get(f"/schedules/{schedule['schedule_id']}").json()["last_world_id"]
    assert world_id and world_id.startswith("w_")
    _wait(lambda: [c for c in dev_client.get(f"/worlds/{world_id}/cards").json() if c["kind"] == "gate"], "gate")
    assert any(e["type"] == "budget.granted" for e in _events(dev_client, world_id))


def test_DEV_HARNESS_d_not_due_fires_nothing(dev_client):
    _schedule(dev_client)
    _grant_policy(dev_client)
    body = dev_client.post(PATH, json={}).json()  # now: the first slot is days away
    assert body["fired"] == 0 and body["tasks"] == []


def test_DEV_HARNESS_d_without_the_l3_grant_budget_policy_the_run_is_not_started(dev_client):
    schedule = _schedule(dev_client)  # no policy: the dev owner has only the L1 send policy
    body = dev_client.post(PATH, json={"as_of": _as_of(schedule)}).json()
    assert [t.get("skipped") for t in body["tasks"]] == ["budget_not_granted"]
    assert dev_client.get(f"/schedules/{schedule['schedule_id']}").json()["last_world_id"] is None


def test_DEV_HARNESS_d_the_body_is_strict(dev_client):
    for bad in ({"as_of": "tomorrow"}, {"as_of": "2026-10-12T09:00:00"}, {"as_of": 1}, {"other": 1}):
        assert dev_client.post(PATH, json=bad).status_code == 422, bad


def test_DEV_HARNESS_d_loopback_host_only(dev_client):
    refused = dev_client.post(PATH, json={}, headers={"host": "evil.example:8080"})
    assert refused.status_code == 400


def test_DEV_HARNESS_d_replay_only_starts_nothing(dev_client):
    from tilo_metering import flags  # noqa: PLC0415

    schedule = _schedule(dev_client)
    _grant_policy(dev_client)
    flags.process_flags().set("replay_only", True, reason="DEV_HARNESS test")
    try:
        response = dev_client.post(PATH, json={"as_of": _as_of(schedule)})
        assert response.status_code != 200 or response.json()["fired"] == 0
    finally:
        flags.process_flags().set("replay_only", False, reason="DEV_HARNESS test done")


def test_DEV_HARNESS_d_production_has_no_such_route():
    paths = {getattr(r, "path", "") for r in production_app.routes}
    assert PATH not in paths and not any(p.startswith("/dev/") for p in paths)
    assert ("POST", "/internal/schedules/tick") in {
        (m, getattr(r, "path", "")) for r in production_app.routes for m in getattr(r, "methods", ())
    }


def test_DEV_HARNESS_d_a_deployed_process_never_registers_it(monkeypatch):
    app = _app()
    with pytest.raises(dev.DevModeRefused):
        dev.install(app, {"K_SERVICE": "tilo-api"})
    assert not any(getattr(r, "path", "") == PATH for r in app.routes)
    assert dev.install_if_enabled(app, {"K_SERVICE": "tilo-api"}) is False
    assert not any(getattr(r, "path", "") == PATH for r in app.routes)


def test_DEV_HARNESS_d_the_real_tick_still_needs_its_google_token(dev_client, monkeypatch):
    monkeypatch.setenv(schedules.ENV_AUDIENCE, "https://tilo.example")
    monkeypatch.setenv(schedules.ENV_CALLER, "scheduler@example.iam.gserviceaccount.com")
    monkeypatch.setenv(schedules.ENV_TASKS_CALLER, "tasks@example.iam.gserviceaccount.com")
    monkeypatch.setenv(schedules.ENV_QUEUE, "projects/p/locations/l/queues/q")
    assert dev_client.post(schedules.TICK_PATH).status_code == 401  # no bearer
    assert dev_client.post(schedules.TICK_PATH, headers={"Authorization": "Bearer not-a-token"}).status_code == 401
