"""CL-INT-5 (EFF-01, PRD 7.1): in dev mode `POST /intake` takes any task text through questions and approaches
with no recordings and no paid call, because `config/models.dev.yaml` serves the Director with a deterministic
fake. Plan compilation (FR-INT-09) is not part of this: nothing here approves."""

from __future__ import annotations

import pathlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tilo_api import deps, dev
from tilo_api.intake import router as intake_router
from tilo_api.tasks import router as tasks_router

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]


@pytest.fixture()
def dev_client(monkeypatch):
    for name in ("LIVE", "K_SERVICE", "CLOUD_RUN_JOB"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TILO_MODELS_FILE", str(dev.DEV_MODELS))
    app = FastAPI()
    app.include_router(intake_router)
    app.include_router(tasks_router)
    dev.install(app, {})
    return TestClient(app, base_url=f"http://localhost:{dev.PORT}")  # the Host dev mode accepts


def _flow(client: TestClient, text: str) -> tuple[dict, dict]:
    response = client.post("/intake", data={"text": text})
    assert response.status_code == 201, response.text
    task = response.json()
    answers = [{"field": q["field"], "answer": None} for q in task["questions"]]  # skip: keep the guess, "Assumed"
    assert (
        client.post(f"/tasks/{task['task_id']}/answers", json={"answers": answers, "brief_edits": {}}).status_code
        == 200
    )
    proposed = client.get(f"/tasks/{task['task_id']}/approaches")
    assert proposed.status_code == 200, proposed.text
    return task, proposed.json()


def test_CL_INT_5_dev_intake_runs_through_questions_and_approaches_with_no_recordings(dev_client):
    assert not (deps.FIXTURES_DIR / "director").exists(), "this test needs a tree with no Director recordings"

    task, proposed = _flow(dev_client, "Prepare the weekly supplier summary.")

    assert task["brief"]["goal"] == "Prepare the weekly supplier summary."
    assert 1 <= len(task["questions"]) <= 3
    approaches = proposed["approaches"]
    assert len(approaches) == 3 and proposed["recommended"] in {a["id"] for a in approaches}
    assert all(a["label"].endswith("(dev)") and a["credits"]["max"] <= 300 for a in approaches)


def test_CL_INT_5_dev_replies_are_deterministic_across_tasks(dev_client):
    first, proposed_first = _flow(dev_client, "Same words.")
    second, proposed_second = _flow(dev_client, "Same words.")
    other, _ = _flow(dev_client, "Different words.")

    assert first["brief"] == second["brief"] and first["questions"] == second["questions"]
    assert proposed_first["approaches"] == proposed_second["approaches"]
    assert other["brief"]["goal"] == "Different words."


def test_CL_INT_5_dev_models_file_is_selected_by_just_dev_api(monkeypatch):
    monkeypatch.setenv("TILO_MODELS_FILE", "unset-below")  # records the original, so dev.main's write is undone too
    monkeypatch.delenv("TILO_MODELS_FILE")
    monkeypatch.setenv("TILO_API_DEV", "1")  # dev.main() sets it in os.environ: monkeypatch must undo that afterwards
    monkeypatch.setattr("uvicorn.run", lambda *a, **k: None)

    dev.main()

    import os

    assert pathlib.Path(os.environ["TILO_MODELS_FILE"]) == REPO_ROOT / "config" / "models.dev.yaml"
    monkeypatch.setenv("TILO_MODELS_FILE", "config/models.nim.yaml")  # a choice the user already made is kept
    dev.main()
    assert os.environ["TILO_MODELS_FILE"] == "config/models.nim.yaml"


def test_CL_INT_5_dev_intake_fails_closed_when_deployed(dev_client, monkeypatch):
    monkeypatch.setenv("K_SERVICE", "tilo-api")
    client = TestClient(dev_client.app, base_url=dev_client.base_url, raise_server_exceptions=False)
    response = client.post("/intake", data={"text": "Anything."})
    assert response.status_code >= 500 and response.status_code != 201


def test_CL_INT_5_request_input_cannot_select_the_fake_director(dev_client, monkeypatch):
    """The models file comes from config/environment only: with the default one, no form field, query parameter
    or header names another, and nothing reaches the fake Director."""
    monkeypatch.delenv("TILO_MODELS_FILE")
    monkeypatch.setattr(
        "tilo_providers.dev_director.DevDirectorProvider.generate",
        lambda *a, **k: pytest.fail("a request reached the dev fake Director"),
    )
    client = TestClient(dev_client.app, base_url=dev_client.base_url, raise_server_exceptions=False)
    selectors = {"models_file": str(dev.DEV_MODELS), "TILO_MODELS_FILE": str(dev.DEV_MODELS), "model": "fake-director"}
    headers = {f"X-{name}": value for name, value in selectors.items()}
    response = client.post("/intake", data={"text": "Anything.", **selectors}, params=selectors, headers=headers)
    assert response.status_code != 201
