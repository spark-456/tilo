"""X-SEC05-SVC: anonymous internal sends fail before configuration or body reads."""

import pytest
from fastapi.testclient import TestClient
from tilo_channels.app import app
from tilo_channels.push_routes import ENV_AUDIENCE, ENV_CALLER, get_sender, get_verifier


@pytest.mark.parametrize("header", [None, "", "Basic junk", "Bearer", "Bearer   ", "Bearer a b"])
def test_X_SEC05_SVC_unconfigured_push_rejects_missing_or_malformed_caller(monkeypatch, header):
    monkeypatch.delenv(ENV_AUDIENCE, raising=False)
    monkeypatch.delenv(ENV_CALLER, raising=False)

    class NoVerify:
        def verify(self, *_):
            pytest.fail("anonymous requests must not verify tokens")

    app.dependency_overrides[get_verifier] = NoVerify
    app.dependency_overrides[get_sender] = lambda: None
    try:
        headers = {} if header is None else {"authorization": header}
        response = TestClient(app).post("/internal/push/send", content=b"not JSON", headers=headers)
        assert response.status_code == 401
    finally:
        app.dependency_overrides.clear()
