"""CL-INT-5d (issue #248 gap 5, EFF-01, HR-1, PRD 14.1): a LOCAL DEV run is paced by a per-unit delay and its units
carry small, honest credits: the cost is metered by the real PriceBook from the dev price file and rides on the unit's
artifact.created event, the credits meter is the sum of the events, and the total stays under the approved cap. The
delay is an asyncio sleep on the run's own thread (no busy loop, no blocked request) and every seam still refuses when
deployed or live."""

from __future__ import annotations

import asyncio
import math
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tilo_api import deps, dev, dev_run, runs
from tilo_api.cards import build_router
from tilo_api.intake import router as intake_router
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
        time.sleep(0.02)
    return value


def _events(client: TestClient, world_id: str) -> list[dict]:
    return list(client.app.dependency_overrides[deps.get_store]().events.get(world_id, []))


def _approve(client: TestClient, cap: float, approach: str | None = None) -> tuple[str, dict]:
    task = client.post("/intake", data={"text": "Prepare the weekly supplier summary."}).json()
    answers = [{"field": q["field"], "answer": None} for q in task["questions"]]
    client.post(f"/tasks/{task['task_id']}/answers", json={"answers": answers, "brief_edits": {}})
    approaches = client.get(f"/tasks/{task['task_id']}/approaches").json()
    body = {"approach_id": approach or approaches["recommended"], "budget_cap": cap}
    response = client.post(f"/tasks/{task['task_id']}/approve", json=body)
    assert response.status_code == 200, response.text
    return response.json()["world_id"], task["brief"]


def _gate(client: TestClient, world_id: str) -> dict:
    cards = _wait(lambda: [c for c in client.get(f"/worlds/{world_id}/cards").json() if c["kind"] == "gate"], "gate")
    return cards[0]


def _finish(client: TestClient, world_id: str, option: str = "approve") -> list[dict]:
    card = _gate(client, world_id)
    assert client.post(f"/worlds/{world_id}/cards/{card['id']}/answer", json={"option": option}).status_code == 200
    _wait(lambda: any(e["type"] == "world.completed" for e in _events(client, world_id)), "world.completed")
    return _events(client, world_id)


def test_CL_INT_5d_the_delay_reads_the_env_var_and_is_clamped():
    name = dev_run.DELAY_ENV
    assert dev_run.unit_delay_s({}) == dev_run.DEFAULT_DELAY_S == 1.5
    assert dev_run.unit_delay_s({name: "2.5"}) == 2.5
    assert dev_run.unit_delay_s({name: "0"}) == 0.0
    assert dev_run.unit_delay_s({name: "-4"}) == 0.0
    assert dev_run.unit_delay_s({name: "999"}) == dev_run.MAX_DELAY_S == 10.0
    for junk in ("", "soon", "nan", "inf", "-inf"):
        assert dev_run.unit_delay_s({name: junk}) == dev_run.DEFAULT_DELAY_S, junk


def test_CL_INT_5d_the_suite_runs_unpaced_unless_a_test_sets_the_delay():
    assert dev_run.unit_delay_s() == 0.0  # conftest sets TILO_DEV_UNIT_DELAY_S=0 for every test


def test_CL_INT_5d_a_unit_waits_the_delay_and_the_wait_never_blocks_the_loop(monkeypatch):
    monkeypatch.setenv(dev_run.DELAY_ENV, "0.4")
    ticks: list[float] = []

    async def ticker() -> None:
        for _ in range(20):
            ticks.append(time.monotonic())
            await asyncio.sleep(0.02)

    async def scenario() -> float:
        started = time.monotonic()
        _, outcome = await asyncio.gather(ticker(), dev_run.DevUnitRunner().run({"title": "T"}, None))
        assert outcome.success
        return time.monotonic() - started

    assert 0.4 <= asyncio.run(scenario()) < 3.0
    assert len(ticks) == 20 and max(b - a for a, b in zip(ticks, ticks[1:], strict=False)) < 0.2  # loop stayed free


def test_CL_INT_5d_a_huge_delay_sleeps_at_most_the_clamp(monkeypatch):
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(dev_run.asyncio, "sleep", fake_sleep)
    monkeypatch.setenv(dev_run.DELAY_ENV, "100000")
    asyncio.run(dev_run.DevUnitRunner().run({"title": "T"}, None))
    assert slept == [10.0]
    monkeypatch.setenv(dev_run.DELAY_ENV, "0")
    asyncio.run(dev_run.DevUnitRunner().run({"title": "T"}, None))
    assert slept == [10.0], "a zero delay does not sleep at all"


def test_CL_INT_5d_a_paced_dev_run_takes_time_and_other_requests_stay_quick(dev_client, monkeypatch):
    monkeypatch.setenv(dev_run.DELAY_ENV, "0.3")
    started = time.monotonic()
    world_id, _ = _approve(dev_client, cap=8)
    slowest = 0.0
    while not [c for c in dev_client.get(f"/worlds/{world_id}/cards").json() if c["kind"] == "gate"]:
        t = time.monotonic()
        dev_client.get(f"/worlds/{world_id}/events")
        slowest = max(slowest, time.monotonic() - t)
        assert time.monotonic() - started < 15, "the gate never came"
        time.sleep(0.02)
    assert time.monotonic() - started >= 1.2, "four units of 0.3 s each come before the gate"
    assert slowest < 0.25, "a request made during the run waited for a unit"


def test_CL_INT_5d_unit_credits_come_from_the_price_book_and_are_small_and_non_zero():
    credits = dev_run.unit_credits()
    assert credits == pytest.approx((2000 * 1.0 + 600 * 4.0) / 1_000_000 / 0.005) == pytest.approx(0.88)
    assert 0 < 4 * credits < 8  # four units fit the smallest cap S-03 offers


@pytest.mark.parametrize(("cap", "approach"), [(8, "quick_overview"), (30, "balanced_review")])
def test_CL_INT_5d_credits_move_with_each_unit_and_stay_under_the_cap(dev_client, cap, approach):
    world_id, _ = _approve(dev_client, cap=cap, approach=approach)
    stream = _finish(dev_client, world_id)

    charged = [e for e in stream if e["credits"]]
    assert {e["type"] for e in charged} == {"artifact.created"}, "only the event that records a unit's work is charged"
    assert [e["credits"] for e in charged] == [pytest.approx(dev_run.unit_credits())] * 4
    assert all(e["credits"] >= 0 and math.isfinite(e["credits"]) for e in stream)
    total = math.fsum(e["credits"] for e in stream)
    completed = next(e for e in stream if e["type"] == "world.completed")
    assert completed["data"]["credits_used"] == pytest.approx(total) and 0 < total <= cap
    assert dev_client.get(f"/worlds/{world_id}/delivery").json()["credits_used"] == pytest.approx(total)
    assert any(e["type"] == "approval.requested" for e in stream[stream.index(charged[0]) :]), "meter moves pre-gate"


def test_CL_INT_5d_a_cap_smaller_than_the_cost_is_never_exceeded(dev_client, monkeypatch):
    monkeypatch.setattr(deps, "min_run_grant", lambda: 0.0)  # the 60-credit floor (BQ-BUDGET-FLOOR-1) would lift cap 1
    world_id, _ = _approve(dev_client, cap=1)
    card = _gate(dev_client, world_id)  # every unit before the gate is done
    dev_client.post(f"/worlds/{world_id}/cards/{card['id']}/answer", json={"option": "hold"})
    assert 0 < math.fsum(e["credits"] for e in _events(dev_client, world_id)) <= 1


def test_CL_INT_5d_the_delivered_title_is_the_briefs_deliverable_title(dev_client):
    world_id, brief = _approve(dev_client, cap=30)
    _finish(dev_client, world_id)
    (artifact,) = dev_client.get(f"/worlds/{world_id}/delivery").json()["artifacts"]
    assert artifact["title"] == brief["deliverables"][0]["title"] == "Draft deliverable (dev)"


def test_CL_INT_5d_the_runner_refuses_when_deployed_or_live(dev_client, monkeypatch):
    for name, value in (("K_SERVICE", "tilo-api"), ("CLOUD_RUN_JOB", ""), ("LIVE", "1")):
        monkeypatch.setenv(name, value)
        with pytest.raises(dev.DevModeRefused):
            asyncio.run(dev_run.DevUnitRunner().run({"title": "T"}, None))
        with pytest.raises(dev.DevModeRefused):
            dev_client.app.dependency_overrides[deps.get_unit_runner]()
        monkeypatch.delenv(name)


def test_CL_INT_5d_the_real_price_file_is_untouched_and_the_dev_one_is_marked_dev(repo_root):
    real = (repo_root / "config" / "prices.yaml").read_text(encoding="utf-8")
    assert "status: set" in real and "dev-unit" not in real  # PL-06: the real file is set; no dev stand-in leaks in
    assert "not a real price" in (repo_root / "config" / "prices.dev.yaml").read_text(encoding="utf-8")
