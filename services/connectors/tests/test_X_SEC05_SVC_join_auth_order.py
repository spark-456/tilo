"""X-SEC05-SVC: anonymous join refuses before configuration or body reads."""

import pytest
from fastapi.testclient import TestClient
from tilo_connectors.app import create_app
from tilo_connectors.host_routes import HostRuntime


@pytest.mark.parametrize("header", [None, "", "Basic junk", "Bearer", "Bearer   ", "Bearer a b"])
def test_X_SEC05_SVC_unconfigured_join_rejects_missing_or_malformed_caller(header):
    class NoVerify:
        def verify(self, *_):
            pytest.fail("anonymous requests must not verify tokens")

    runtime = HostRuntime({}, verifier=NoVerify())
    headers = {} if header is None else {"authorization": header}
    response = TestClient(create_app(runtime)).post("/internal/meeting-host/join", content=b"not JSON", headers=headers)
    assert response.status_code == 401
    assert response.json() == {"error": "unauthenticated"}
