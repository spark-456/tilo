"""A quiz serves only checked, recorded sources to its owning web session."""

import copy
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tilo_api import deps, events
from tilo_api.quiz_apps import router
from tilo_api.world_writer import PREPLAN_LAYOUT, WorldWriterAdapter
from tilo_harness.store import MemoryStore
from tilo_memory.artifacts import ArtifactStore, MemoryBlobBackend, MemoryMetaBackend, NewVersion, Origin, Scope
from tilo_providers.safety import FakeSafetyProvider
from tilo_sandbox_web.fetch_fixtures import PAPERS

SPEC = json.loads(
    (Path(__file__).resolve().parents[3] / "contracts/fixtures/appspec/valid/true_false_one_question.json").read_text()
)
WORLD, OWNER, RUN = "w_quiz", "u_owner", "r_quiz"
NOW = datetime(2026, 10, 11, tzinfo=UTC)


def make_case():
    scope = Scope(deps.ORG_ID, WORLD, OWNER)
    artifacts = ArtifactStore(
        MemoryMetaBackend(),
        MemoryBlobBackend(),
        clock=lambda: NOW,
        redactor=lambda text: text,
        archive_lookup=lambda _s, _r: None,
        alert_sink=lambda _a: None,
        screener=FakeSafetyProvider(),
    )
    source = artifacts.put(scope, NewVersion("application/pdf", PAPERS["paper-1.pdf"], RUN, Origin("upload")))
    spec = copy.deepcopy(SPEC)
    spec["questions"][0]["source"] = {"artifact": source.ref, "page": 1}
    quiz = artifacts.put(
        scope,
        NewVersion(
            "application/json",
            json.dumps(spec).encode(),
            RUN,
            Origin("unit", "U1", "A_s1"),
            idempotency_key=f"{RUN}:U1:0:0",
        ),
    )
    layout = copy.deepcopy(PREPLAN_LAYOUT)
    layout["semantic"]["agents"] += [{"id": "A_s1", "rank": "specialist"}, {"id": "A_v1", "rank": "verifier"}]
    state = deps.Store(worlds={WORLD: deps.WorldRecord(OWNER, {}, run_id=RUN, layout=layout)})
    writer = WorldWriterAdapter(state, MemoryStore(), clock=lambda: NOW)
    for item in (source, quiz):
        writer.append(
            WORLD,
            {
                "id": events.new_part_id(),
                "type": "artifact.created",
                "actor": "A_s1",
                "target": item.artifact_id,
                "summary": "An item was made.",
                "vis": "all",
                "data": {
                    "artifact": item.ref,
                    **{k: item.record[k] for k in ("content_sha256", "media_type", "size_bytes")},
                },
            },
        )
    made = writer.append(
        WORLD,
        {
            "id": events.new_part_id(),
            "type": "app.spec",
            "actor": "A_s1",
            "target": quiz.artifact_id,
            "summary": "Quiz stored.",
            "vis": "all",
            "data": {"spec": quiz.ref},
        },
    )
    writer.append(
        WORLD,
        {
            "id": events.new_part_id(),
            "type": "app.tested",
            "actor": "A_v1",
            "target": quiz.artifact_id,
            "summary": "Quiz checked.",
            "vis": "all",
            "cause": made["id"],
            "data": {"spec": quiz.ref, "passed": True},
        },
    )
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides.update(
        {
            deps.get_store: lambda: state,
            deps.get_artifact_store: lambda: artifacts,
            deps.get_event_writer: lambda: writer,
            deps.get_current_principal: lambda: deps.Principal(OWNER, "owner", WORLD),
        }
    )
    return app, state, writer, quiz, source, spec


@pytest.mark.parametrize(
    "flaw",
    [
        "none",
        "other_owner",
        "viewer",
        "email",
        "other_world",
        "missing_spec",
        "failed",
        "self_review",
        "not_verifier",
        "unrecorded_source",
        "unrecorded_quiz",
    ],
)
def test_owner_quiz_requires_recorded_sources_and_independent_pass(flaw):
    app, state, writer, quiz, source, spec = make_case()
    try:
        stream = state.events[WORLD]
        if flaw in {"other_owner", "viewer", "email", "other_world"}:
            principal = deps.Principal(
                "u_other" if flaw == "other_owner" else OWNER,
                "viewer" if flaw == "viewer" else "owner",
                "w_else" if flaw == "other_world" else WORLD,
                channel="email" if flaw == "email" else "web",
                full_session=True,
            )
            app.dependency_overrides[deps.get_current_principal] = lambda: principal
        elif flaw == "missing_spec":
            state.events[WORLD] = [e for e in stream if e["type"] != "app.spec"]
        elif flaw == "failed":
            stream[-1]["data"]["passed"] = False
        elif flaw in {"self_review", "not_verifier"}:
            stream[-1]["actor"] = "A_s1" if flaw == "self_review" else "u_other"
        elif flaw == "unrecorded_source":
            state.events[WORLD] = [e for e in stream if e.get("data", {}).get("artifact") != source.ref]
        elif flaw == "unrecorded_quiz":
            state.events[WORLD] = [e for e in stream if e.get("data", {}).get("artifact") != quiz.ref]
        with TestClient(app) as client:
            url = f"/worlds/{WORLD}/apps/{quiz.artifact_id}"
            response = client.get(url)
            assert response.status_code == (200 if flaw == "none" else 404), response.text
            if flaw == "none":
                assert response.json()["spec"] == spec
                assert response.json()["publishers"] == {}
                assert response.headers["cache-control"] == "no-store"
                assert client.get(url).status_code == 200
                assert sum(e["type"] == "app.deployed" for e in state.events[WORLD]) == 1
            else:
                assert not any(e["type"] == "app.deployed" for e in state.events[WORLD])
    finally:
        writer.reopen()
