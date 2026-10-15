"""The normal Run pipeline binds default web reads, renders and checks an owner quiz."""

import asyncio
import base64
import copy
import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from tilo_api import deps
from tilo_api.layout import build_layout
from tilo_api.quiz_apps import router as quiz_router
from tilo_api.runs import Run, Seams
from tilo_api.world_writer import WorldWriterAdapter
from tilo_archive import LocalDirStore, RunArchive
from tilo_browser.fetch import detect_media_type
from tilo_connectors import InMemoryOutboxStore
from tilo_connectors.registry import ConnectorRegistry
from tilo_evals.web_replay import SANDBOX_HOST, SandboxTransport, ScriptedModel, _resolve
from tilo_harness.skills import SkillRegistry
from tilo_harness.store import MemoryStore
from tilo_memory.artifacts import ArtifactStore, MemoryBlobBackend, MemoryMetaBackend
from tilo_planning.compiler import _with_deliver
from tilo_providers.replay import RecordReplayProvider, recording_key
from tilo_providers.safety import FakeSafetyProvider
from tilo_providers.search import (
    FakeSearchProvider,
    SearchRecordReplayProvider,
    SearchResult,
    SearchSource,
    search_recording_key,
)

ROOT = Path(__file__).resolve().parents[3]
WORLD, RUN, OWNER = "w_default_web", "r_default_web", "u_default_web"
NOW = datetime(2026, 10, 11, tzinfo=UTC)


class RecordingModel:
    def __init__(self, role, replies, root, seed):
        self.model, self.seed, self.role = ScriptedModel(replies), seed, role
        self.requests = []
        self.replay = RecordReplayProvider(role, "fixture", self.no_live, root, force_replay=True)

    def no_live(self):
        raise AssertionError("No live provider")

    def generate(self, request):
        self.requests.append(request)
        if self.seed:
            reply = self.model.generate(request)
            key = recording_key(self.role, "fixture", request)
            self.replay._write_recording(self.replay._path(key), key, reply)
        return self.replay.generate(request)


def execute_case(root, monkeypatch, seed, confirmed=True):
    state = deps.Store(worlds={WORLD: deps.WorldRecord(OWNER, {}, run_id=RUN)})
    writer = WorldWriterAdapter(state, MemoryStore(), clock=lambda: NOW)

    def open_archive(*, org_id, run_id):
        return RunArchive(
            LocalDirStore(root / ("seed" if seed else "replay")),
            org_id=org_id,
            run_id=run_id,
            redactor=lambda value: value,
            clock=lambda: NOW,
        )

    def archived(scope, ref):
        assert scope.world_id == WORLD
        return next(
            (
                json.dumps(r["payload"])
                for r in open_archive(org_id=deps.ORG_ID, run_id=RUN).records()
                if f"{RUN}/{r['seq']}" == ref
            ),
            None,
        )

    ids = iter(range(1, 20))
    artifacts = ArtifactStore(
        MemoryMetaBackend(),
        MemoryBlobBackend(),
        clock=lambda: NOW,
        redactor=lambda text: text,
        archive_lookup=archived,
        alert_sink=lambda _: None,
        screener=FakeSafetyProvider(),
        new_id=lambda: f"art_default_{next(ids)}",
        file_sniffer=lambda raw: detect_media_type(raw, url="https://source.test/f", host="source.test")[0],
    )
    brief = {
        "goal": "Practice from the sources",
        "deliverables": [
            {"title": "Source report", "format": "pdf"},
            {"title": "Practice quiz", "format": "app"},
        ],
    }
    plan = json.loads((ROOT / "contracts/fixtures/plan/valid/two_approaches_email_send_gated.json").read_text())
    plan["gates"] = []
    plan["budget_cap"] = 100
    plan["units"] = _with_deliver(
        [
            {
                "id": "U1",
                "unit_type": "research",
                "title": "Read sources",
                "role": "specialist",
                "district": "D1",
                "skills": ["web-research"],
                "actions": [],
                "connectors": [],
                "depends_on": [],
            }
        ],
        brief,
    )
    source = {"artifact_id": "art_default_1", "version": 1}
    spec = json.loads((ROOT / "contracts/fixtures/appspec/valid/true_false_one_question.json").read_text())
    spec["questions"][0]["source"] = {"artifact": source, "page": 1}
    report = {
        "title": "Source report",
        "date": "2026-10-11",
        "sections": [
            {"heading": "Sources", "blocks": [{"type": "paragraph", "text": "The fictional paper was read."}]},
        ],
    }
    urls = [f"https://{SANDBOX_HOST}/papers/{name}" for name in ("paper-1.pdf", "answer-key.pdf", "wrong-magic.pdf")]
    models = {
        "specialist": RecordingModel(
            "specialist",
            [
                [("web_search", {"query": "practice sources"})],
                [("fetch_url", {"url": url}) for url in urls],
                "Sources read.",
            ],
            root,
            seed,
        ),
        "writer": RecordingModel("writer", [json.dumps(report), json.dumps(spec)], root, seed),
        "verifier": RecordingModel("verifier", ["Sources checked.", json.dumps({"confirmed": confirmed})], root, seed),
    }
    result = SearchResult(
        query="practice sources",
        answer="Recorded sources",
        queries=["practice sources"],
        sources=[SearchSource(title="Paper", domain=SANDBOX_HOST, redirect_url=urls[0])],
        profile_id="fixture",
        usage={"search_queries": 1},
    )

    def no_live():
        raise AssertionError("Replay never constructs a live search provider")

    search_replay = SearchRecordReplayProvider("fixture", no_live, root, force_replay=True)
    if seed:
        key = search_recording_key("fixture", "practice sources", None)
        search_replay._write(root / "search-recordings" / f"{key}.json", key, result, FakeSearchProvider())
        fetch_root = root / "fetch-recordings"
        (fetch_root / "dns").mkdir(parents=True)
        (fetch_root / "http").mkdir()
        addresses = _resolve(SANDBOX_HOST, 443)
        dns_key = hashlib.sha256(f"{SANDBOX_HOST}:443".encode()).hexdigest()
        (fetch_root / "dns" / f"{dns_key}.json").write_text(
            json.dumps(
                {
                    "host": SANDBOX_HOST,
                    "port": 443,
                    "addresses": addresses,
                }
            )
        )
        transport = SandboxTransport()
        for path in [
            "/robots.txt",
            *["/papers/" + name for name in ("paper-1.pdf", "answer-key.pdf", "wrong-magic.pdf")],
        ]:
            response = transport.send_get(path_and_query=path, max_bytes=25 * 1024 * 1024)
            url = f"https://{SANDBOX_HOST}:443{path}"
            key = hashlib.sha256(url.encode()).hexdigest()
            (fetch_root / "http" / f"{key}.json").write_text(
                json.dumps(
                    {
                        "url": url,
                        "pinned_ip": addresses[0],
                        "status": response.status_code,
                        "headers": response.headers,
                        "body": base64.b64encode(response.body).decode(),
                        "sha256": hashlib.sha256(response.body).hexdigest(),
                    }
                )
            )
    search = SimpleNamespace(
        search=lambda _role, query, budget: SimpleNamespace(search_result=search_replay.search(query), budget=budget)
    )
    monkeypatch.setattr(deps, "_worker_models", lambda mode: models)
    monkeypatch.setattr(deps, "_seam_router", lambda mode, meter=None: search)
    monkeypatch.setattr(deps, "get_safety", lambda mode: FakeSafetyProvider())
    monkeypatch.setattr(deps, "FIXTURES_DIR", root)
    clear = SimpleNamespace(generate=lambda _: SimpleNamespace(text='{"ask":false}'))
    seams = Seams(
        compiler=lambda **_: copy.deepcopy(plan),
        layout_builder=build_layout,
        runner=deps.get_unit_runner("replay", today=lambda: date(2026, 10, 11)),
        resolver=lambda **_: {},
        skills=SkillRegistry(ROOT / "skills"),
        connectors=ConnectorRegistry({}),
        adapters={},
        outbox_store=InMemoryOutboxStore(),
        writer=writer,
        must_ask_providers={role: clear for role in models},
        artifacts=artifacts,
        redactor=lambda text: text,
        open_archive=open_archive,
        team=lambda: None,
    )
    task = deps.TaskRecord(OWNER, WORLD, RUN, brief, brief, [], 0, approaches=plan["approaches"])
    run = Run(state, task, plan["approaches"][0], 100, seams)
    asyncio.run(run._execute())
    return state, artifacts, writer, models


def test_normal_api_run_records_native_sources_pdf_and_checked_quiz(tmp_path, monkeypatch):
    for seed in (True, False):
        state, artifacts, writer, models = execute_case(tmp_path, monkeypatch, seed)
        stream = state.events[WORLD]
        assert not [e for e in stream if e["type"] == "world.failed"], [
            (e["type"], e["summary"], e["data"]) for e in stream
        ]
        assert stream[-1]["type"] == "world.completed"
        assert len(models["writer"].requests) == 2
        assert all(len(request.parts) == 3 for request in models["writer"].requests)
        created = [e for e in stream if e["type"] == "artifact.created"]
        assert sum(e["data"]["media_type"] == "application/pdf" for e in created) == 3
        (tested,) = [e for e in stream if e["type"] == "app.tested"]
        (spec_event,) = [e for e in stream if e["type"] == "app.spec"]
        assert tested["data"]["passed"] is True and tested["actor"] != spec_event["actor"]
        app = FastAPI()
        app.include_router(quiz_router)
        app.dependency_overrides.update(
            {
                deps.get_store: lambda: state,
                deps.get_artifact_store: lambda: artifacts,
                deps.get_event_writer: lambda: writer,
                deps.get_current_principal: lambda: deps.Principal(OWNER, "owner", WORLD),
            }
        )
        with TestClient(app) as client:
            response = client.get(f"/worlds/{WORLD}/apps/{tested['target']}")
            assert response.status_code == 200, response.text
            assert response.json()["publishers"] == {"art_default_1": SANDBOX_HOST}
        assert sum(e["credits"] for e in stream) == 0


def test_unconfirmed_quiz_fails_before_delivery(tmp_path, monkeypatch):
    state, artifacts, writer, models = execute_case(tmp_path, monkeypatch, True, confirmed=False)
    stream = state.events[WORLD]
    (tested,) = [e for e in stream if e["type"] == "app.tested"]
    assert tested["data"]["passed"] is False
    assert stream[-1]["type"] == "world.failed"
    assert not any(e["type"] == "artifact.delivered" and e["target"] == tested["target"] for e in stream)
    assert not any(e["type"] in {"world.completed", "app.deployed", "data.transfer"} for e in stream)
