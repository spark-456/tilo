"""Shared fixtures and plain data factories for services/api acceptance tests (ticket ST-3a,
FR-HIL-07, FR-HIL-09, SEC-07, docs/security/p4-policy-invariants.md PI-13).

No business logic lives here (root CLAUDE.md test-writer rule): every helper below either loads
a contract schema unchanged or returns a literal dict/dataclass shaped like the contract or the
API this ticket pins (services/api/tests/API_ST3a.md). `tilo_api.deps` (Principal, Store,
get_current_principal, get_store) does not exist yet; importing it is what makes every test in
this directory fail for the right reason until the builder ships it — the same pattern
packages/policy/tests/conftest.py uses for `tilo_policy`.

This directory has no __init__.py, so pytest's default "prepend" import mode puts it on
sys.path when collecting any test_*.py here, the same plain-module-import pattern
packages/policy/tests/conftest.py and packages/providers/tests/conftest.py use.
"""

from __future__ import annotations

import pytest
from _api_lib import FakeEventWriter, make_store, make_writer
from fastapi.testclient import TestClient
from tilo_api import app, deps


@pytest.fixture()
def store() -> deps.Store:
    return make_store()


@pytest.fixture()
def writer(store: deps.Store) -> FakeEventWriter:
    """The in-memory stand-in for "the harness is the only writer of events" (PRD 15.3, PI-18):
    tilo-api hands it unstamped event parts; it stamps id/seq/ts/run_id and appends to
    store.events. Built on the same store instance the test holds, so store.events reflects every
    write immediately."""
    return make_writer(store)


@pytest.fixture()
def client(store: deps.Store, writer: FakeEventWriter):
    """A TestClient over the real `tilo_api.app`, with the store and event writer injected and no
    principal set yet -- individual tests set `app.dependency_overrides[deps.get_current_principal]`
    for the role they want, then reset dependency_overrides at teardown so tests do not leak into
    each other."""
    app.dependency_overrides[deps.get_store] = lambda: store
    app.dependency_overrides[deps.get_event_writer] = lambda: writer
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
