"""Rig for the RT grounding tests (ADR-0049): the TSW-1 people rig, an in-memory artifact store, a fake embedder and
a `Grounding` over them. Not a test module."""

from __future__ import annotations

import hashlib
import math
from datetime import UTC, datetime
from typing import Any

from _tsw1_lib import ASHA, LAUNCH, WORLD, Rig
from tilo_api import deps
from tilo_api.grounding import ApiSourceRules, Grounding
from tilo_memory.artifacts import (
    ArtifactStore,
    MemoryBlobBackend,
    MemoryMetaBackend,
    NewVersion,
    Origin,
    Scope,
)
from tilo_memory.chunks import ChunkConfig, ChunkStore
from tilo_memory.chunks_backends import MemoryChunkBackend
from tilo_providers.safety import FakeSafetyProvider

ORG = deps.ORG_ID
RUN = "r_launch_1"


class WordEmbedder:
    profile, dimensions = "embed-fake", 64

    def __init__(self) -> None:
        self.fail = False
        self.calls: list[str] = []

    def embed(self, texts: Any, task: str) -> list[list[float]]:
        if self.fail:
            raise RuntimeError("embed role down")
        self.calls.append(task)
        out = []
        for text in texts:
            v = [0.0] * 64
            for word in text.lower().split():
                v[int(hashlib.sha256(word.encode()).hexdigest(), 16) % 64] += 1.0
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / n for x in v])
        return out


def artifacts() -> ArtifactStore:
    return ArtifactStore(
        MemoryMetaBackend(),
        MemoryBlobBackend(),
        clock=lambda: datetime(2026, 10, 16, tzinfo=UTC),
        redactor=lambda text: text,
        archive_lookup=lambda *_: None,
        alert_sink=lambda _: None,
        screener=FakeSafetyProvider(),
    )


class GroundingRig(Rig):
    def __init__(self) -> None:
        super().__init__()
        self.puts = 0
        self.artifacts, self.embedder, self.backend = artifacts(), WordEmbedder(), MemoryChunkBackend()
        rules = ApiSourceRules(self.people, self.store, self.artifacts)
        chunks = ChunkStore(self.backend, self.embedder, rules, config=ChunkConfig())
        self.grounding = Grounding(chunks, ORG, self.people, self.store, self.artifacts)

    def deliver(self, text: str, *, origin: str = "unit", world: str = WORLD, owner: str = ASHA) -> Any:
        unit = origin == "unit"
        self.puts += 1
        return self.artifacts.put(
            Scope(ORG, world, owner),
            NewVersion(
                "text/markdown",
                text.encode(),
                RUN,
                Origin("unit", "U1", "A_writer") if unit else Origin(origin),
                idempotency_key=f"{RUN}:U1:0:{self.puts}" if unit else None,
            ),
        )

    def search(self, user: str, query: str) -> list[Any]:
        return self.grounding.store.search(ORG, user, query)


def team_pin(pin_id: str = "pb_launch", *, title: str = "Launch checklist", team: str | None = LAUNCH) -> dict:
    scope = {"kind": "team", "team": team} if team else {"kind": "personal", "user": ASHA}
    return {
        "id": pin_id, "org_id": ORG, "scope": scope, "title": title, "body": "ship the launch plan on time",
        "kind": "note", "url": None, "owner": None, "due": None, "status": "active",
        "created_by": {"by": "person", "ref": ASHA, "at": "2026-10-10T09:00:00.000Z"}, "set_up_by": ASHA,
        "source": None, "confirmed_by": None, "flagged": False,
        "history": [{"at": "2026-10-10T09:00:00.000Z", "by": ASHA, "change": "created", "status": "active"}],
        "created_at": "2026-10-10T09:00:00.000Z", "updated_at": "2026-10-10T09:00:00.000Z",
    }  # fmt: skip
