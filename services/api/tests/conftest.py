"""Shared pytest fixtures for services/api acceptance tests: FR-HIL-09/SEC-07 (roles and
redaction) and FR-INT-01/FR-INT-02 (intake, PRD 7.1).

No business logic lives here (root CLAUDE.md test-writer rule): every helper below either loads
a contract schema unchanged or returns a literal dict/dataclass shaped like the contract or an API
this repo pins (services/api/tests/API_ST3a.md for redaction; the HTTP contract documented in
`_api_contracts_lib.py` for intake). Fixture builders and schema validation live in `_api_lib.py`
(redaction) and `_api_contracts_lib.py` (intake), kept out of this file under package-unique module
names: every test directory in the repo has its own conftest.py, so `from conftest import ...`
resolves to whichever one was imported first when the whole suite runs together -- the same
global-bare-module-name reason `_api_contracts_lib.py`'s own docstring gives for its name.

This directory has no __init__.py, so pytest's default "prepend" import mode puts it on
sys.path when collecting any test_*.py here, the same plain-module-import pattern
packages/policy/tests/conftest.py and packages/providers/tests/conftest.py use.
"""

from __future__ import annotations

import pathlib

import pytest
from _api_contracts_lib import build_registry, make_safety_provider
from _api_lib import FakeEventWriter, make_store, make_writer
from fastapi.testclient import TestClient
from tilo_api import app, deps
from tilo_api.intake import get_safety

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]


@pytest.fixture(scope="session")
def repo_root() -> pathlib.Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def registry(repo_root: pathlib.Path):
    return build_registry(repo_root)


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
    """A TestClient over the real `tilo_api.app`, with the store, the event writer and a
    deterministic fake safety provider injected: the app itself ships no safety provider (the
    screen belongs to packages/providers) and `/intake` fails closed with 503 without one. No
    principal is set yet -- individual tests set
    `app.dependency_overrides[deps.get_current_principal]` for the role they want -- and
    `dependency_overrides` is cleared at teardown so tests do not leak into each other."""
    safety = make_safety_provider()
    app.dependency_overrides[deps.get_store] = lambda: store
    app.dependency_overrides[deps.get_event_writer] = lambda: writer
    app.dependency_overrides[get_safety] = lambda: safety
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
