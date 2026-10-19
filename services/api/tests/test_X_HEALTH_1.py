"""Offline public configuration inventory: names and arbitrary values never escape."""

import pytest
from fastapi.testclient import TestClient
from tilo_api import app, health_deps


@pytest.mark.parametrize("path", ["/healthz/deps", "/health/deps"])
def test_unconfigured_inventory_is_public_and_has_no_dependency_io(monkeypatch, path):
    monkeypatch.setattr(health_deps.os, "environ", {})
    response = TestClient(app).get(path)
    assert response.status_code == 200
    assert response.json() == {
        "api_store": "unconfigured",
        "artifacts_store": "unconfigured",
        "archive_store": "unconfigured",
        "skills_store": "unconfigured",
        "firestore_project_configured": False,
        "artifacts_bucket_configured": False,
        "archive_bucket_configured": False,
        "connectors_url_configured": False,
        "live_mode": False,
    }


def test_configured_inventory_only_exposes_fixed_kinds_and_booleans(monkeypatch):
    monkeypatch.setattr(
        health_deps.os,
        "environ",
        {
            "TILO_API_STORE": "firestore",
            "TILO_ARTIFACTS_STORE": "gcs",
            "TILO_ARCHIVE_STORE": "gcs",
            "TILO_SKILLS_STORE": "firestore",
            "TILO_FIRESTORE_PROJECT": "private-project-canary",
            "TILO_ARTIFACTS_BUCKET": "private-artifacts-canary",
            "TILO_ARCHIVE_BUCKET": "private-archive-canary",
            "TILO_CONNECTORS_URL": "https://private-canary.example/secret",
            "LIVE": "1",
            "UNRELATED_SECRET": "secret-canary",
        },
    )
    response = TestClient(app).get("/healthz/deps")
    assert response.status_code == 200
    assert response.json() == {
        "api_store": "firestore",
        "artifacts_store": "gcs",
        "archive_store": "gcs",
        "skills_store": "firestore",
        "firestore_project_configured": True,
        "artifacts_bucket_configured": True,
        "archive_bucket_configured": True,
        "connectors_url_configured": True,
        "live_mode": True,
    }
    assert "canary" not in response.text


def test_arbitrary_store_values_never_echo_and_live_is_exact(monkeypatch):
    monkeypatch.setattr(
        health_deps.os,
        "environ",
        {
            "TILO_API_STORE": "secret-canary",
            "TILO_ARTIFACTS_STORE": "secret-canary",
            "TILO_ARCHIVE_STORE": "secret-canary",
            "TILO_SKILLS_STORE": "secret-canary",
            "TILO_CONNECTORS_URL": "   ",
            "LIVE": "true",
        },
    )
    data = health_deps.dependency_configuration()
    assert all(data[key] == "invalid" for key in ("api_store", "artifacts_store", "archive_store", "skills_store"))
    assert data["live_mode"] is False
    assert data["connectors_url_configured"] is False
    assert "canary" not in str(data)
