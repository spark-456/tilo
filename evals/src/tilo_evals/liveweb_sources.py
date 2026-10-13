"""Recorded providers and fetched-source fixtures for the free live-web rehearsal."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tilo_harness.tools import ToolResult
from tilo_memory.artifacts import NewVersion, Origin
from tilo_providers.media import MediaPart
from tilo_providers.replay import RecordReplayProvider, recording_key
from tilo_providers.search import (
    FakeSearchProvider,
    SearchRecordReplayProvider,
    SearchResult,
    SearchSource,
    redact_query,
    search_recording_key,
)

from .web_replay import SANDBOX_HOST, ScriptedModel

REPO = Path(__file__).resolve().parents[3]
FIXTURES = REPO / "evals/fixtures/liveweb-complete"
WORLD, RUN, OWNER = "w_liveweb", "r_gate_1", "u_gate_owner"
QUERY = "Northbridge fictional past paper and answer key"
NOW = datetime(2026, 10, 11, tzinfo=UTC)


def no_live():
    raise AssertionError("This replay never constructs a live provider")


class RecordedModel(ScriptedModel):
    def __init__(self, role: str, replies: list[Any], seed: bool, fixtures: Path = FIXTURES):
        super().__init__(replies)
        self.role, self.seed = role, seed
        self.replay = RecordReplayProvider(role, "fixture", no_live, fixtures, force_replay=True)

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

    def __init__(self, seed: bool, fixtures: Path = FIXTURES):
        self.provider = SearchRecordReplayProvider("fixture", no_live, fixtures, force_replay=True)
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
            self.provider._write(fixtures / "search-recordings" / f"{key}.json", key, result, FixtureSearch())

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
