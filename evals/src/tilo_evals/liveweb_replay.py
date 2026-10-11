"""Complete free live-web rehearsal: search, native files, PDF, and owner-only quiz (no LIVE)."""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import os
from collections.abc import Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from tilo_api import deps
from tilo_api.quiz_apps import router, source_loader
from tilo_api.world_writer import PREPLAN_LAYOUT, WorldWriterAdapter
from tilo_archive import LocalDirStore, RunArchive
from tilo_browser.fetch import detect_media_type
from tilo_harness.executor import UnitContext
from tilo_harness.outputs import keep
from tilo_harness.quiz import verify_answers
from tilo_harness.skills import LoadedSkill
from tilo_harness.store import MemoryStore
from tilo_harness.tool_runner import ToolUnitRunner
from tilo_harness.tools import MemoryToolArchive, ToolRegistry, ToolResult
from tilo_harness.unit_prompt import UpstreamItem
from tilo_memory.artifacts import ArtifactStore, MemoryBlobBackend, MemoryMetaBackend, NewVersion, Origin, Scope
from tilo_providers.media import MediaPart
from tilo_providers.replay import RecordReplayProvider, recording_key
from tilo_providers.safety import FakeSafetyProvider
from tilo_providers.search import (
    FakeSearchProvider,
    SearchRecordReplayProvider,
    SearchResult,
    SearchSource,
    redact_query,
    search_recording_key,
)

from .web_replay import SANDBOX_HOST, FixtureWeb, ScriptedModel

REPO = Path(__file__).resolve().parents[3]
FIXTURES = REPO / "fixtures/liveweb-complete"
WORLD, RUN, OWNER = "w_liveweb", "r_gate_1", "u_gate_owner"
QUERY = "Northbridge fictional past paper and answer key"
NOW = datetime(2026, 10, 11, tzinfo=UTC)


def no_live():
    raise AssertionError("This replay never constructs a live provider")


class RecordedModel(ScriptedModel):
    def __init__(self, role: str, replies: list[Any], seed: bool):
        super().__init__(replies)
        self.role, self.seed = role, seed
        self.replay = RecordReplayProvider(role, "fixture", no_live, FIXTURES, force_replay=True)

    def generate(self, request):
        if self.seed:
            response = super().generate(request)
            key = recording_key(self.role, "fixture", request)
            self.replay._write_recording(self.replay._path(key), key, response)
        else:
            self.requests.append(request)
        return self.replay.generate(request)


class FixtureSearch(FakeSearchProvider):
    def redact(self, text: str) -> str:
        return redact_query(text)


class SearchTool:
    name, description = "web_search", "Search for public source URLs."
    tier, external_content, side_effect = "T1", True, False
    input_schema: Mapping[str, Any] = {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
        "additionalProperties": False,
    }

    def __init__(self, seed: bool):
        self.provider = SearchRecordReplayProvider("fixture", no_live, FIXTURES, force_replay=True)
        if seed:
            result = SearchResult(
                query=QUERY,
                answer="Fictional past paper and answer key.",
                sources=[
                    SearchSource(
                        title="Paper", domain=SANDBOX_HOST, redirect_url=f"https://{SANDBOX_HOST}/papers/paper-1.pdf"
                    )
                ],
                queries=[QUERY],
                profile_id="fixture",
                usage={"search_queries": 1},
            )
            key = search_recording_key("fixture", QUERY, None)
            self.provider._write(FIXTURES / "search-recordings" / f"{key}.json", key, result, FixtureSearch())

    def run(self, args):
        return ToolResult(self.provider.search(args["query"]).model_dump_json())


class NativeFetchTool:
    name, description = "fetch_url", "Fetch and screen a public file; return its recorded artifact and native bytes."
    tier, external_content, side_effect = "T1", True, False
    input_schema: Mapping[str, Any] = {
        "type": "object",
        "properties": {"url": {"type": "string"}},
        "required": ["url"],
        "additionalProperties": False,
    }

    def __init__(self, web, artifacts, scope, writer):
        self.web, self.artifacts, self.scope, self.writer = web, artifacts, scope, writer
        self.files = []

    def run(self, args):
        got = self.web.service.fetch(
            args["url"], allow_hosts=(SANDBOX_HOST,), org_id=self.scope.org_id, run_id=RUN, unit_id="U1"
        )
        raw = self.web.service.archive_store.get_bytes(self.scope.org_id, RUN, got.sha256)
        part = MediaPart(mime_type=got.media_type, data=raw)
        version = self.artifacts.put(
            self.scope,
            NewVersion(
                got.media_type,
                raw,
                RUN,
                Origin("fetch", "U1", "A_s1"),
                sources=({"id": "source", "archive_ref": got.archive_ref},),
                idempotency_key=f"{RUN}:U1:0:f{len(self.files)}",
            ),
        )
        self.files.append((version, part))
        self.writer.append(
            WORLD,
            {
                "id": _id("source", str(len(self.files))),
                "type": "artifact.created",
                "actor": "A_s1",
                "target": version.artifact_id,
                "summary": "A source was fetched.",
                "vis": "all",
                "data": {
                    "artifact": version.ref,
                    **{k: version.record[k] for k in ("content_sha256", "media_type", "size_bytes")},
                },
            },
        )
        return ToolResult(json.dumps({"artifact": version.ref, "archive_ref": got.archive_ref}), parts=(part,))


def _id(*parts):
    from tilo_api.events import stable_part_id

    return stable_part_id("liveweb-replay", *parts)


async def _run(web: FixtureWeb, seed: bool) -> dict[str, Any]:
    scope = Scope(deps.ORG_ID, WORLD, OWNER)
    archive = RunArchive(
        LocalDirStore(web.root), org_id=scope.org_id, run_id=RUN, redactor=lambda data: data, clock=lambda: NOW
    )
    counter = iter(range(1, 20))

    def archived(_scope, ref):
        for record in archive.records():
            if f"{RUN}/{record['seq']}" == ref:
                return json.dumps(record["payload"])
        return None

    artifacts = ArtifactStore(
        MemoryMetaBackend(),
        MemoryBlobBackend(),
        clock=lambda: NOW,
        redactor=lambda text: text,
        archive_lookup=archived,
        alert_sink=lambda _a: None,
        screener=FakeSafetyProvider(),
        new_id=lambda: f"art_liveweb_{next(counter)}",
        file_sniffer=lambda raw: detect_media_type(raw, url="https://source.test/file", host="source.test")[0],
    )
    layout = json.loads(json.dumps(PREPLAN_LAYOUT))
    layout["semantic"]["agents"] += [
        {"id": "A_s1", "rank": "specialist"},
        {"id": "A_s2", "rank": "specialist"},
        {"id": "A_v1", "rank": "verifier"},
    ]
    state = deps.Store(worlds={WORLD: deps.WorldRecord(OWNER, {}, run_id=RUN, layout=layout)})
    writer = WorldWriterAdapter(state, MemoryStore(), clock=lambda: NOW)
    fetch = NativeFetchTool(web, artifacts, scope, writer)
    search = SearchTool(seed)
    urls = [f"https://{SANDBOX_HOST}/papers/{path}" for path in ("paper-1.pdf", "answer-key.pdf", "wrong-magic.pdf")]
    specialist = RecordedModel(
        "specialist",
        [[("web_search", {"query": QUERY})], [("fetch_url", {"url": url}) for url in urls], "Sources read."],
        seed,
    )
    skill = LoadedSkill(
        "web-research", "1.0.0", "Find and cite the papers.", "0" * 64, tools_allowed=("web_search", "fetch_url")
    )
    runner = ToolUnitRunner(
        {"specialist": specialist},
        tools=ToolRegistry([search, fetch]),
        safety=FakeSafetyProvider(),
        archive=MemoryToolArchive(),
        today=lambda: date(2026, 10, 11),
    )
    research = await runner.run_unit(
        {"id": "U1", "title": "Read the sources", "role": "specialist", "unit_type": "research"},
        UnitContext("A_s1", (skill,)),
    )
    assert research.outcome.success
    load = source_loader(artifacts, scope, state.events[WORLD])
    quiz: dict[str, Any] = {
        "v": "1.0",
        "kind": "quiz",
        "title": "Fictional practice",
        "theme": "metropolis",
        "timer": {"seconds": 60},
        "questions": [
            {
                "id": "q1",
                "stem": "What value stabilizes the clockwork valve?",
                "options": {"a": "7 units", "b": "42.0 units"},
                "answer": "b",
                "source": {"artifact": fetch.files[0][0].ref, "page": 1},
            }
        ],
    }
    report_spec = {
        "title": "Practice report: fictional past paper",
        "date": "2026-10-11",
        "sections": [
            {
                "heading": "Summary",
                "blocks": [
                    {
                        "type": "paragraph",
                        "text": "The clockwork valve stabilizes at 42.0 units; see the cited paper and key.",
                    }
                ],
            },
            {"heading": "Sources", "blocks": [{"type": "bullets", "bullets": urls}]},
        ],
    }
    report_model = RecordedModel("writer-report", [json.dumps(report_spec)], seed)
    quiz_model = RecordedModel("writer-quiz", [json.dumps(quiz)], seed)
    native = list(specialist.requests[-1].parts or [])
    kept = []
    for index, (model, fmt) in enumerate(((report_model, "pdf"), (quiz_model, "app")), start=2):
        unit = {"id": f"U{index}", "title": "Practice deliverable", "role": "writer", "unit_type": "deliver"}
        run = ToolUnitRunner(
            {"writer": model},
            quiz_sources=load,
            today=lambda: date(2026, 10, 11),
            request_options={"writer": {"parts": native}},
        )
        outcome = await run.run(
            unit,
            UnitContext(
                "A_s2",
                (),
                brief={"deliverables": [{"format": fmt}]},
                upstream=(
                    UpstreamItem("U1", "Sources", json.dumps(quiz["questions"][0]["source"]), (), "clean", True),
                ),
            ),
        )
        assert outcome.success, outcome.summary
        sourced = tuple(
            dataclasses.replace(
                output,
                sources=tuple(
                    {"id": f"source{i}", "archive_ref": v.record["sources"][0]["archive_ref"]}
                    for i, (v, _p) in enumerate(fetch.files)
                ),
            )
            for output in outcome.outputs
        )
        made = keep(
            sourced,
            artifacts=artifacts,
            scope=scope,
            archive=archive,
            redact=lambda text: text,
            run_id=RUN,
            unit=unit,
            worker="A_s2",
            events=[],
            max_attempts=3,
            recorded=lambda _id: 0,
        )[0].version
        writer.append(
            WORLD,
            {
                "id": _id(fmt),
                "type": "artifact.created",
                "actor": "A_s2",
                "target": made.artifact_id,
                "summary": "A deliverable was made.",
                "vis": "all",
                "data": {
                    "artifact": made.ref,
                    **{k: made.record[k] for k in ("content_sha256", "media_type", "size_bytes")},
                },
            },
        )
        kept.append(made)
    spec_ref = kept[1].ref
    writer.append(
        WORLD,
        {
            "id": _id("spec"),
            "type": "app.spec",
            "actor": "A_s2",
            "target": kept[1].artifact_id,
            "summary": "The quiz specification was stored.",
            "vis": "all",
            "data": {"spec": spec_ref},
        },
    )
    verifier = RecordedModel("verifier", ['{"confirmed":true}'], seed)
    confirmed = verify_answers(quiz, verifier, load)
    writer.append(
        WORLD,
        {
            "id": _id("tested"),
            "type": "app.tested",
            "actor": "A_v1",
            "target": kept[1].artifact_id,
            "summary": "The quiz answer was checked.",
            "vis": "all",
            "cause": _id("spec"),
            "data": {"spec": spec_ref, "passed": confirmed},
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
    with TestClient(app) as client:
        served = client.get(f"/worlds/{WORLD}/apps/{kept[1].artifact_id}")
        assert served.status_code == 200, served.text
        again = client.get(f"/worlds/{WORLD}/apps/{kept[1].artifact_id}")
        assert again.status_code == 200
        app.dependency_overrides[deps.get_current_principal] = lambda: deps.Principal("u_stranger", "owner", WORLD)
        denied = client.get(f"/worlds/{WORLD}/apps/{kept[1].artifact_id}")
    facts = {
        "search_outcome": research.calls[0].outcome,
        "native_types": [p.mime_type for p in native],
        "native_bytes_match_archive": all(artifacts.read(scope, v.ref) == part.data for v, part in fetch.files),
        "report_cites_fetched_urls": set(urls) == {r["payload"]["source"]["ref"] for r in archive.records()},
        "report": {
            "media_type": kept[0].record["media_type"],
            "origin": kept[0].record["origin"]["kind"],
            "magic": artifacts.read(scope, kept[0].ref)[:5].decode(),
        },
        "quiz": {
            "media_type": kept[1].record["media_type"],
            "origin": kept[1].record["origin"]["kind"],
            "answer_checked": confirmed,
            "owner_status": served.status_code,
            "other_owner_status": denied.status_code,
            "publisher": served.json()["publishers"],
        },
        "app_events": [e["type"] for e in state.events[WORLD] if e["type"].startswith("app.")],
        "verifier_received_pdf": verifier.requests[0].parts[0].sha256 == native[0].sha256,
        "credits": 0,
    }
    writer.reopen()
    return facts


def run_complete_case(*, seed: bool = False) -> dict[str, Any]:
    if os.environ.get("LIVE") == "1":
        raise RuntimeError("Unset LIVE before running the free rehearsal")
    web = FixtureWeb()
    try:
        return asyncio.run(_run(web, seed))
    finally:
        web.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="Generate fake-provider recordings; never sets LIVE")
    args = parser.parse_args()
    print(json.dumps(run_complete_case(seed=args.write), sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
