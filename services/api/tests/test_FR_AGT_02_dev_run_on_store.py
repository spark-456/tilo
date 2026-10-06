"""FR-AGT-02 / FR-MEM-06 T4 (ADR-0018 section 5 ticket 4; tests/API_FR_AGT_02_T4.md), dev mode: the local dev run puts
each unit's synthetic Markdown on an in-memory artifact store through the executor, so the ids in its stream are the
store's (never `art_dev_...`), and no request or environment value selects anything else. Fakes only: dev mode makes
no network or paid call (EFF-01) and each dev stand-in refuses when deployed or live."""

from __future__ import annotations

import asyncio
import hashlib
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


def _run_to_completion(client: TestClient) -> str:
    task = client.post("/intake", data={"text": "Prepare the weekly supplier summary."}).json()
    answers = [{"field": q["field"], "answer": None} for q in task["questions"]]
    client.post(f"/tasks/{task['task_id']}/answers", json={"answers": answers, "brief_edits": {}})
    approaches = client.get(f"/tasks/{task['task_id']}/approaches").json()
    body = {"approach_id": approaches["recommended"], "budget_cap": 30}
    response = client.post(f"/tasks/{task['task_id']}/approve", json=body)
    assert response.status_code == 200, response.text
    world_id = response.json()["world_id"]
    cards = _wait(lambda: [c for c in client.get(f"/worlds/{world_id}/cards").json() if c["kind"] == "gate"], "gate")
    client.post(f"/worlds/{world_id}/cards/{cards[0]['id']}/answer", json={"option": "approve"})
    _wait(lambda: any(e["type"] == "world.completed" for e in _events(client, world_id)), "world.completed")
    return world_id


def test_FR_AGT_02_the_dev_unit_runner_returns_synthetic_markdown_not_a_named_artifact() -> None:
    outcome = asyncio.run(dev_run.DevUnitRunner().run({"title": "T"}, None))  # CL-INT-5d calls it exactly so

    assert outcome.success is True and outcome.artifact_refs == (), "a runner names no artifact (ADR-0018 s6)"
    (output,) = outcome.outputs
    assert output.media_type == "text/markdown" and type(output.content) is bytes and output.content.strip()
    assert output.parent is None and output.sources == ()
    assert outcome.credits == pytest.approx(dev_run.unit_credits()), "metered by the real PriceBook, as before"


def test_FR_AGT_02_a_dev_runs_items_are_on_the_dev_store_with_the_stores_ids_and_hashes(dev_client) -> None:
    from tilo_memory.artifacts import Scope  # noqa: PLC0415

    world_id = _run_to_completion(dev_client)

    stream = _events(dev_client, world_id)
    created = [e for e in stream if e["type"] == "artifact.created"]
    assert len(created) == 4, "one synthetic item per unit, as before"
    store = dev_client.app.dependency_overrides[deps.get_artifact_store]()
    scope = Scope(org_id=deps.ORG_ID, world_id=world_id, owner=dev.DEV_OWNER)
    unit_of = {e["target"]: e["data"]["unit"] for e in stream if e["type"] == "agent.assigned"}
    for event in created:
        ref = event["data"]["artifact"]
        assert not ref["artifact_id"].startswith("art_dev_"), "the store mints ids; the dev runner does not"
        stored = store.read(scope, ref)
        assert stored.decode("utf-8").strip(), "synthetic Markdown, not empty"
        record = store.head(scope, ref).record
        assert record["media_type"] == "text/markdown" and record["owner"] == dev.DEV_OWNER
        assert event["data"]["content_sha256"] == hashlib.sha256(stored).hexdigest() == record["content_sha256"]
        assert event["data"]["size_bytes"] == len(stored) == record["size_bytes"]
        assert record["origin"] == {"kind": "unit", "unit": unit_of[event["actor"]], "agent": event["actor"]}
    delivered = dev_client.get(f"/worlds/{world_id}/delivery").json()["artifacts"]
    assert [a["id"] for a in delivered] and all(
        store.head(scope, {"artifact_id": a["id"], "version": a["version"]}) is not None for a in delivered
    ), "a delivered item is one the store holds"


def test_FR_AGT_02_two_dev_worlds_never_share_an_item(dev_client) -> None:
    first, second = _run_to_completion(dev_client), _run_to_completion(dev_client)

    ids = {
        world: {
            e["data"]["artifact"]["artifact_id"] for e in _events(dev_client, world) if e["type"] == "artifact.created"
        }
        for world in (first, second)
    }
    assert len(ids[first]) == len(ids[second]) == 4 and ids[first].isdisjoint(ids[second])


def test_FR_AGT_02_the_dev_artifact_store_is_one_in_memory_store_that_refuses_when_deployed_or_live(
    dev_client, monkeypatch
) -> None:
    from tilo_memory.artifacts import ArtifactStore  # noqa: PLC0415

    seams = dev_client.app.dependency_overrides
    store = seams[deps.get_artifact_store]()
    assert isinstance(store, ArtifactStore) and seams[deps.get_artifact_store]() is store, (
        "the run and a reader share it"
    )
    for name, value in (("K_SERVICE", "tilo-api"), ("CLOUD_RUN_JOB", ""), ("LIVE", "1")):
        monkeypatch.setenv(name, value)
        with pytest.raises(dev.DevModeRefused):
            seams[deps.get_artifact_store]()
        monkeypatch.delenv(name)
