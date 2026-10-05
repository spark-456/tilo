"""SEC-05, issue #410: until sign-in, Firestore and the harness are wired, an unset dependency refuses the call
with a 401 or 503 and a short body, never a 500 with a traceback (which the run_5xx_ratio alert would count)."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from tilo_api import app, deps


@pytest.mark.parametrize(
    ("seam", "status"),
    [(deps.get_current_principal, 401), (deps.get_store, 503), (deps.get_event_writer, 503)],
)
def test_SEC_05_an_unset_seam_refuses_with_a_status_not_an_exception(seam, status):
    with pytest.raises(HTTPException) as refused:
        seam()
    assert refused.value.status_code == status


def test_SEC_05_an_anonymous_call_to_the_production_app_is_a_401_with_no_traceback(monkeypatch):
    for name in ("TILO_API_DEV", "LIVE", "K_SERVICE", "CLOUD_RUN_JOB"):
        monkeypatch.delenv(name, raising=False)
    saved = dict(app.dependency_overrides)
    app.dependency_overrides.clear()
    try:
        client = TestClient(app)  # raise_server_exceptions stays True: a leaked exception fails the test
        for method, path in [("POST", "/intake"), ("GET", "/worlds/w_x/events"), ("POST", "/worlds/w_x/pause")]:
            response = client.request(method, path)
            assert response.status_code in {401, 503}, (method, path, response.status_code)
            assert "Traceback" not in response.text
    finally:
        app.dependency_overrides.update(saved)
