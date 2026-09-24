"""PRD 6.2: `tilo-api` (Cloud Run) is the sessions/tasks/cards/... service.
Ticket P0-01 stands up its skeleton: GET /healthz -> 200 {"status": "ok"}.

Requires fastapi + the tilo_api package, which only exist once the uv
workspace (services/api) is built -- run via `uv run pytest` once `just
setup` has created the workspace. Not importable with only
`--with pytest --with pyyaml`, so this test fails at collection with a clear
ModuleNotFoundError until then; that is failing for the right reason.
"""
from __future__ import annotations

import importlib


def test_PRD_6_2_api_healthz_returns_ok() -> None:
    fastapi_testclient = importlib.import_module("fastapi.testclient")
    tilo_api = importlib.import_module("tilo_api")

    client = fastapi_testclient.TestClient(tilo_api.app)
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
