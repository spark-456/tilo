"""Fixtures for the P8-07 Sandbox Web acceptance tests (PRD 6.2)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from tilo_sandbox_web import app


@pytest.fixture(scope="session")
def client():
    return TestClient(app)
