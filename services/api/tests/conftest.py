"""Shared fixtures and plain data factories for services/api acceptance tests (ticket FR-HIL-09,
SEC-07).

No business logic lives here (root CLAUDE.md test-writer rule): every helper below either loads
a contract schema unchanged or returns a literal dict/dataclass shaped like the contract or the
API this ticket pins (services/api/tests/API_ST3a.md). `tilo_api.deps` (Principal, Store,
get_current_principal, get_store) does not exist yet on `main`; importing it is what makes every
test in this directory fail for the right reason until the builder ships it — the same pattern
packages/policy/tests/conftest.py uses for `tilo_policy`.

This directory has no __init__.py, so pytest's default "prepend" import mode puts it on
sys.path when collecting any test_*.py here, the same plain-module-import pattern
packages/policy/tests/conftest.py and packages/providers/tests/conftest.py use.
"""

from __future__ import annotations

import pytest
from _api_lib import make_store
from fastapi.testclient import TestClient
from tilo_api import app, deps


@pytest.fixture()
def store() -> deps.Store:
    return make_store()


@pytest.fixture()
def client(store: deps.Store):
    """A TestClient over the real `tilo_api.app`, with the store injected and no principal set
    yet -- individual tests set `app.dependency_overrides[deps.get_current_principal]` for the
    role they want, then reset dependency_overrides at teardown so tests do not leak into each
    other."""
    app.dependency_overrides[deps.get_store] = lambda: store
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
