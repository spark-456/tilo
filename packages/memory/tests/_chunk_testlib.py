"""Doubles for the chunk store tests (RT-01 to RT-08): a bag-of-words embedder and rule tables the test edits."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from tilo_memory.chunks import ChunkConfig, ChunkStore, SourceDoc
from tilo_memory.chunks_backends import MemoryChunkBackend

ORG = "org_tilo"
ALICE, BOB, CARA = "u_alice", "u_bob", "u_cara"
TEAM = "tm_design"
NOW = datetime(2026, 10, 16, 9, 0, tzinfo=UTC)


class WordEmbedder:
    """Unit vectors from hashed words: equal text, equal vector; shared words, nearby vectors. No network."""

    profile, dimensions = "embed-fake", 64

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], str]] = []

    def embed(self, texts: Sequence[str], task: str) -> list[list[float]]:
        self.calls.append((list(texts), task))
        out = []
        for text in texts:
            vector = [0.0] * 64
            for word in text.lower().split():
                vector[int(hashlib.sha256(word.encode()).hexdigest(), 16) % 64] += 1.0
            length = math.sqrt(sum(x * x for x in vector)) or 1.0
            out.append([x / length for x in vector])
        return out


class Rules:
    """People, memberships and what each chunk's source still allows; tests change these to revoke."""

    def __init__(self) -> None:
        self.people = {ALICE, BOB, CARA}
        self.teams: dict[str, list[str]] = {}
        self.denied: set[str] = set()  # chunk ids whose source no longer allows a read
        self.gone_ids: set[str] = set()

    def is_person(self, org_id: str, user_id: str) -> bool:
        return org_id == ORG and user_id in self.people

    def member_teams(self, org_id: str, user_id: str) -> list[str]:
        return list(self.teams.get(user_id, []))

    def readable(self, org_id: str, caller: str, chunk: Any) -> bool:
        return chunk["id"] not in self.denied

    def gone(self, org_id: str, chunk: Any) -> bool:
        return chunk["id"] in self.gone_ids


class SpyBackend(MemoryChunkBackend):
    def __init__(self) -> None:
        super().__init__()
        self.queries: list[tuple[str, str]] = []

    def nearest(self, org_id: str, field: str, value: str, profile: str, vector: Sequence[float], limit: int) -> Any:
        self.queries.append((field, value))
        return super().nearest(org_id, field, value, profile, vector, limit)


def make_store(**kwargs: Any) -> tuple[ChunkStore, SpyBackend, WordEmbedder, Rules]:
    backend, embedder, rules = SpyBackend(), WordEmbedder(), Rules()
    config = kwargs.pop("config", ChunkConfig())
    store = ChunkStore(backend, embedder, rules, config=config, clock=lambda: NOW, **kwargs)
    return store, backend, embedder, rules


def doc(
    owner: str, text: str, *, kind: str = "pin", source_id: str = "pb_one", team: str | None = None, **kw: Any
) -> SourceDoc:
    version = None if kind in ("pin", "memory_item") else 1
    fields: dict[str, Any] = {
        "org_id": ORG, "owner": owner, "team_id": team, "world_id": None, "kind": kind, "source_id": source_id,
        "version": version, "label": "A label", "text": text,
    }  # fmt: skip
    return SourceDoc(**{**fields, **kw})
