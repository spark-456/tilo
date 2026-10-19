"""PROD-WIRE slice 1a, ADR-0026 decision 1 ("no config, another value or a bad project answers 503 `not_configured`
on both seams, never cached, never a fallback to memory; `K_SERVICE` alone opens nothing") and test_SEC_05.

Deployed means `K_SERVICE` is set. The real app, signed in, with no store or writer override, answers 503
`not_configured` through a real route and builds no Firestore client. These pass today and must stay green once
`get_store` and `get_event_writer` read `TILO_API_STORE` per request.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from tilo_api import app, deps

OWNER, WORLD = "u_pw1_owner", "w_pw1_world"
CONFIGS = {
    "no config": {},
    "memory is not a deployed value": {"TILO_API_STORE": "memory"},
    "firestore without a project": {"TILO_API_STORE": "firestore"},
    "firestore with a bad project": {"TILO_API_STORE": "firestore", "TILO_FIRESTORE_PROJECT": "Not A Project"},
}


@pytest.fixture
def deployed(monkeypatch: pytest.MonkeyPatch):
    from google.cloud import firestore

    built: list[object] = []
    monkeypatch.setattr(firestore, "Client", lambda *a, **k: built.append((a, k)))
    for name in ("TILO_API_DEV", "LIVE", "CLOUD_RUN_JOB", "TILO_API_STORE", "TILO_FIRESTORE_PROJECT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("FIRESTORE_EMULATOR_HOST", raising=False)
    monkeypatch.setenv("K_SERVICE", "tilo-api")
    saved = dict(app.dependency_overrides)
    app.dependency_overrides.clear()
    app.dependency_overrides[deps.get_current_principal] = lambda: deps.Principal(
        user_id=OWNER, role="owner", world_id=WORLD
    )
    yield built
    app.dependency_overrides.clear()
    app.dependency_overrides.update(saved)


@pytest.mark.parametrize("config", CONFIGS.values(), ids=CONFIGS.keys())
def test_PROD_WIRE_1a_a_deployed_get_store_is_503_not_configured_through_a_real_route(
    deployed, monkeypatch: pytest.MonkeyPatch, config: dict[str, str]
) -> None:
    for name, value in config.items():
        monkeypatch.setenv(name, value)
    client = TestClient(app, raise_server_exceptions=True)
    for _ in range(2):  # a refusal is never cached
        response = client.get(f"/worlds/{WORLD}/events")
        assert (response.status_code, response.json()) == (503, {"detail": "not_configured"})
    with pytest.raises(HTTPException) as refused:
        deps.get_store()
    assert (refused.value.status_code, refused.value.detail) == (503, "not_configured")
    assert deployed == []


@pytest.mark.parametrize("config", CONFIGS.values(), ids=CONFIGS.keys())
def test_PROD_WIRE_1a_a_deployed_get_event_writer_is_503_not_configured_through_a_real_route(
    deployed, monkeypatch: pytest.MonkeyPatch, config: dict[str, str]
) -> None:
    for name, value in config.items():
        monkeypatch.setenv(name, value)
    store = deps.Store(worlds={WORLD: deps.WorldRecord(owner=OWNER, districts={})})
    app.dependency_overrides[deps.get_store] = lambda: store  # only the writer seam is left unwired
    client = TestClient(app, raise_server_exceptions=True)
    for _ in range(2):
        response = client.post(f"/worlds/{WORLD}/pause")
        assert (response.status_code, response.json()) == (503, {"detail": "not_configured"})
    with pytest.raises(HTTPException) as refused:
        deps.get_event_writer()
    assert (refused.value.status_code, refused.value.detail) == (503, "not_configured")
    assert deployed == [] and store.events == {} and store.pending_events == {}
