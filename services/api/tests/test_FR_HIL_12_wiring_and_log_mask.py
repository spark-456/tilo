"""FR-HIL-12: share routes wired into the app, the lifetime is config, the access log never holds a token."""

from __future__ import annotations

import datetime as dt
import logging

from fastapi.testclient import TestClient
from tilo_api import app, sharing


def test_FR_HIL_12_the_app_serves_the_share_routes_and_refuses_unsigned_callers():
    paths = app.openapi()["paths"]  # the real app, not a test double
    assert {"/share/{token}", "/share/{token}/answer", "/worlds/{world_id}/cards/{card_id}/share"} <= set(paths)
    client = TestClient(app)
    assert client.get("/share/anything").status_code == 401  # production default: no sign-in, no token lookup
    assert client.post("/share/anything/answer", json={"option": "approve"}).status_code == 401


def test_FR_HIL_12_the_link_lifetime_comes_from_config_not_code(tmp_path, monkeypatch):
    assert sharing.link_ttl() == dt.timedelta(hours=24)  # config/sharing.yaml
    for body, expected in (("sharing: {link_ttl_hours: 2}", 2), ("sharing: {link_ttl_hours: 9999}", 24), ("[", 24)):
        config = tmp_path / "sharing.yaml"
        config.write_text(body, encoding="utf-8")
        monkeypatch.setattr(sharing, "SHARING_CONFIG", config)
        assert sharing.link_ttl() == dt.timedelta(hours=expected)


def test_FR_HIL_12_the_access_log_masks_the_token_in_the_path():
    secret = "tok" + "en-" + "x" * 20  # assembled at runtime: a fake secret
    record = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d', None, None)
    record.args = ("127.0.0.1:1", "GET", f"/share/{secret}/answer", "1.1", 200)
    mask = next(f for f in logging.getLogger("uvicorn.access").filters if isinstance(f, sharing._MaskToken))

    assert mask.filter(record)

    assert secret not in record.getMessage() and "/share/<redacted>/answer" in record.getMessage()
