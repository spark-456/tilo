from fastapi import FastAPI, Response
from fastapi.testclient import TestClient
from tilo_api import cors


def test_meeting_host_signal_is_exposed_only_when_present(monkeypatch):
    monkeypatch.setattr("tilo_api.access.enforced", lambda: True)
    app = FastAPI()

    @app.get("/connectors")
    def connectors(response: Response):
        response.headers["X-Tilo-Meeting-Host"] = "not_configured"
        return {"connectors": []}

    @app.get("/other")
    def other():
        return {}

    client = TestClient(cors.ProductionCors(app))
    headers = {"Origin": cors.PRODUCTION_ORIGINS[0]}
    response = client.get("/connectors", headers=headers)
    assert response.headers["access-control-allow-origin"] == cors.PRODUCTION_ORIGINS[0]
    assert response.headers["access-control-expose-headers"] == "Retry-After, X-Tilo-Meeting-Host"
    assert response.headers["X-Tilo-Meeting-Host"] == "not_configured"
    assert client.get("/other", headers=headers).headers["access-control-expose-headers"] == "Retry-After"
    assert (
        "access-control-allow-origin" not in client.get("/connectors", headers={"Origin": "https://bad.test"}).headers
    )
