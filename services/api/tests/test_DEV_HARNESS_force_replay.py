"""DEV-HARNESS (e): a dev-only, test-only way to force "models unavailable" so the NFR-22/NFR-24 replay offer can be
driven end to end. `TILO_DEV_FORCE_REPLAY=1` is honoured ONLY by `dev.install` (TILO_API_DEV=1, so never deployed or
live); it sets the same process-wide `replay_only` flag the real switch uses, so the 503 `replay_only: true` path runs
unchanged. Nothing we ship sets it."""

from __future__ import annotations

import pathlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_CL_INT_5d_dev_run_pacing import _app
from tilo_api import dev
from tilo_metering import InMemoryFlagStore
from tilo_metering import flags as flag_module

ENV = "TILO_DEV_FORCE_REPLAY"
REPO = pathlib.Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def _own_flags(monkeypatch):
    for name in ("LIVE", "K_SERVICE", "CLOUD_RUN_JOB", "TILO_API_DEV", ENV):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(flag_module, "_process_flags", InMemoryFlagStore())  # restored after the test
    monkeypatch.setenv("TILO_MODELS_FILE", str(dev.DEV_MODELS))


def _dev_client(env: dict[str, str]) -> TestClient:
    app: FastAPI = _app()
    dev.install(app, env)
    return TestClient(app, base_url=f"http://localhost:{dev.PORT}")


def test_DEV_HARNESS_e_without_the_env_nothing_changes():
    client = _dev_client({})
    assert flag_module.process_flags().get("replay_only") is False
    assert client.post("/intake", data={"text": "Prepare the weekly supplier summary."}).status_code == 200


def test_DEV_HARNESS_e_with_the_env_the_replay_offer_is_the_unchanged_503():
    client = _dev_client({ENV: "1"})
    assert flag_module.process_flags().get("replay_only") is True  # the same flag the real switch sets
    response = client.post("/intake", data={"text": "Prepare the weekly supplier summary."})
    assert response.status_code == 503
    assert response.json()["replay_only"] is True and "replay" in response.json()["detail"].lower()


@pytest.mark.parametrize("value", ["", "0", "true", "yes", " 1", "2"])
def test_DEV_HARNESS_e_only_the_exact_value_one_forces_replay(value):
    _dev_client({ENV: value})
    assert flag_module.process_flags().get("replay_only") is False


def test_DEV_HARNESS_e_deployed_dev_mode_is_refused_and_the_env_is_never_applied():
    for deployed in ({"K_SERVICE": "tilo-api"}, {"CLOUD_RUN_JOB": ""}, {"LIVE": "1"}):
        with pytest.raises(dev.DevModeRefused):
            dev.install(_app(), {ENV: "1", "TILO_API_DEV": "1", **deployed})
        assert flag_module.process_flags().get("replay_only") is False


def test_DEV_HARNESS_e_without_dev_mode_the_env_is_ignored_even_when_set_in_cloud_run():
    app = _app()
    assert dev.install_if_enabled(app, {ENV: "1", "K_SERVICE": "tilo-api"}) is False
    assert dev.install_if_enabled(app, {ENV: "1"}) is False
    assert flag_module.process_flags().get("replay_only") is False


def test_DEV_HARNESS_e_nothing_we_ship_sets_it():
    shipped = [REPO / "justfile", *(REPO / "infra").rglob("*"), *(REPO / ".github").rglob("*")]
    shipped += [p for p in (REPO / "services").glob("*/Dockerfile")] + list((REPO / "config").rglob("*"))
    hits = [p for p in shipped if p.is_file() and ENV in p.read_text(encoding="utf-8", errors="ignore")]
    assert hits == [], f"{ENV} must never be set by a shipped config, script or workflow: {hits}"
