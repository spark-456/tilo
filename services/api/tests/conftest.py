"""Pytest fixtures for ticket FR-INT-01/FR-INT-02 `tilo-api` HTTP-surface acceptance tests
(PRD 7.1). Fixture builders and schema validation live in `_api_contracts_lib.py` (see its
module docstring for why: this file is auto-loaded by pytest under the bare module name
`"conftest"`, which collides with `packages/planning/tests/conftest.py` in the same
`uv run pytest` session if helpers are imported back out of it with `from conftest import ...`).

HTTP contract this pass fixes (the builder's target; `packages/planning`'s own tests fix the
underlying `tilo_planning.intake.submit_intake` contract this route is expected to call):

    POST /intake  multipart/form-data
      text: str            (form field)
      files: UploadFile[]  (repeated form field, 0..10 entries)

    201 application/json ->
      {
        "task_id": str, "world_id": str, "run_id": str,
        "event": <world.requested TiloEvent, schema-valid>,
        "files": [
          {"filename": str, "status": "ok", "safety_flagged": bool,
           "artifact": {"artifact_id": str, "version": int},
           "origin": {"source": "upload", "filename": str, "sha256": str,
                      "received_at": str, "task_id": str}},
          ...
        ]
      }

    422 application/json (over limit or disallowed type; FR-INT-01 "rejected with a clear
    reason, nothing stored") -> {"error": <non-empty reason string>}

    This is a deliberate app-level rejection shape for a *business-rule* rejection, not
    FastAPI/Pydantic's own default validation-error body -- the builder wires a handler for it
    rather than relying on the framework default, so this contract does not depend on FastAPI's
    internal error format.
"""

from __future__ import annotations

import pathlib

import pytest
from _api_contracts_lib import build_registry

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]


@pytest.fixture(scope="session")
def repo_root() -> pathlib.Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def registry(repo_root: pathlib.Path):
    return build_registry(repo_root)


@pytest.fixture()
def client():
    """The app with the deterministic fake safety provider injected: the app itself ships none
    (the screen belongs to packages/providers) and fails closed with 503 without one."""
    import tilo_api
    from _api_contracts_lib import make_safety_provider
    from fastapi.testclient import TestClient
    from tilo_api.intake import get_safety

    safety = make_safety_provider()
    tilo_api.app.dependency_overrides[get_safety] = lambda: safety
    yield TestClient(tilo_api.app)
    tilo_api.app.dependency_overrides.pop(get_safety, None)
