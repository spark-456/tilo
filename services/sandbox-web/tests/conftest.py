"""Fixtures for the P8-07 Sandbox Web acceptance tests (PRD 6.2
`tilo-sandbox-web`; SC-01, SC-06, E-RED, E-RES). Ticket spec: SE
orchestrator's "## P8-07" section names `tilo_sandbox_web:app` as the
public FastAPI app -- tests import it as-is and drive it through
`fastapi.testclient.TestClient`, the same way a browser worker or the eval
harness would.

`tilo_sandbox_web` does not exist yet, so `from tilo_sandbox_web import app`
raises ModuleNotFoundError, which every test in this directory needs (via
this fixture) to collect. That is the expected failure for this ticket: no
production code lands on `tests/P8-07`.

Seed content lives at services/sandbox-web/seed/*.yaml -- fixture data the
tests need, excluded from the ticket's hand-written line-count limit (SE
rule 0.19). Its shape (slug, name, kind, pages, ...) follows the P8-07 spec
literally; per-page fields beyond that are this test-writer's stub for the
generic templates the builder will write.
"""

from __future__ import annotations

import pytest


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient
    from tilo_sandbox_web import app

    return TestClient(app)
