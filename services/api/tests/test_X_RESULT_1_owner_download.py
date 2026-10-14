"""X-RESULT-1: recorded run output is downloadable only by its owner."""

from datetime import UTC, datetime

import pytest
from _prod_wire_2b_lib import FakeBucket
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tilo_api import deps
from tilo_api.results import result_store, router
from tilo_api.run_stores import GcsBlobBackend
from tilo_memory.artifacts import ArtifactStore, MemoryMetaBackend, NewVersion, Origin, Scope
from tilo_providers.safety import FakeSafetyProvider

OWNER, WORLD, RUN = "u_owner", "w_result", "r_result"


def make_case():
    artifacts = ArtifactStore(
        MemoryMetaBackend(),
        GcsBlobBackend(FakeBucket()),
        clock=lambda: datetime(2026, 10, 14, tzinfo=UTC),
        redactor=lambda text: text,
        archive_lookup=lambda *_: None,
        alert_sink=lambda _: None,
        screener=FakeSafetyProvider(),
    )
    item = artifacts.put(
        Scope(deps.ORG_ID, WORLD, OWNER),
        NewVersion(
            "application/json",
            b'{"result":"Replay report"}',
            RUN,
            Origin("unit", "U1", "A_s1"),
            idempotency_key=f"{RUN}:U1:0:0",
        ),
    )
    state = deps.Store(worlds={WORLD: deps.WorldRecord(OWNER, {}, run_id=RUN)})
    state.events[WORLD] = [{"type": "artifact.created", "data": {"artifact": item.ref}}]
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides.update(
        {
            deps.get_store: lambda: state,
            deps.get_artifact_store: lambda: artifacts,
            result_store: lambda: lambda: artifacts,
            deps.get_current_principal: lambda: deps.Principal(OWNER, "owner", WORLD),
        }
    )
    return app, state, item


@pytest.mark.parametrize(
    "flaw", ["none", "other_user", "viewer", "email", "other_world", "unfinished", "unrecorded", "wrong_run", "corrupt"]
)
def test_X_RESULT_1_download_recorded_bytes_no_store_owner_only(flaw):
    app, state, quiz = make_case()
    stream = state.events[WORLD]
    stream.extend(
        [
            {"type": "artifact.delivered", "data": {"artifact": quiz.ref, "format": "json"}},
            {"type": "world.completed", "data": {"credits_used": 0}},
        ]
    )
    if flaw in {"other_user", "viewer", "email", "other_world"}:

        def storage_must_not_open():
            raise AssertionError("Unauthorized requests must not open artifact storage")

        app.dependency_overrides[result_store] = lambda: storage_must_not_open
        principal = deps.Principal(
            "u_other" if flaw == "other_user" else OWNER,
            "viewer" if flaw == "viewer" else "owner",
            "w_else" if flaw == "other_world" else WORLD,
            channel="email" if flaw == "email" else "web",
        )
        app.dependency_overrides[deps.get_current_principal] = lambda: principal
    elif flaw == "unfinished":
        stream.pop()
    elif flaw == "unrecorded":
        state.events[WORLD] = [e for e in stream if e["type"] != "artifact.created"]
    elif flaw == "wrong_run":
        state.worlds[WORLD].run_id = "r_else"
    elif flaw == "corrupt":
        artifacts = app.dependency_overrides[deps.get_artifact_store]()
        artifacts.read = lambda *_: (_ for _ in ()).throw(ValueError("corrupt"))
    with TestClient(app) as client:
        response = client.get(f"/worlds/{WORLD}/result")
    assert response.status_code == (200 if flaw == "none" else 404)
    if flaw == "none":
        artifacts = app.dependency_overrides[deps.get_artifact_store]()
        assert response.content == artifacts.read(Scope(deps.ORG_ID, WORLD, OWNER), quiz.ref)
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["content-disposition"].startswith("attachment;")
