"""Shared helpers for the FR-MTG-02 (transcript ingest) acceptance tests: the fixtures, a real `ArtifactStore` over the
memory backends with the deterministic safety fake as its screener, and the schema check against
contracts/transcript.schema.json (jsonschema, not only pydantic)."""

from __future__ import annotations

import pathlib
from datetime import UTC, datetime
from typing import Any

from _fr_mtg_17_lib import assert_valid_transcript
from _planning_contracts_lib import make_safety_provider
from tilo_memory.artifacts import ArtifactStore, MemoryBlobBackend, MemoryMetaBackend, Scope
from tilo_planning.transcript_ingest import TranscriptIngest, ingest_transcript

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures" / "mtg02"
MEETING_ID = "mt_fixture02"
SCOPE = Scope(org_id="org_t02", world_id="w_t02", owner="u_t02")
RUN_ID = "r_ingest_02"
TS = "2026-10-08T09:30:00.000Z"
# The one meeting every clean fixture encodes: (speaker, text) in order; the timed formats share the offsets.
MEETING: list[tuple[str, str]] = [
    ("Priya Shah", "Let's start with the roadmap review."),
    ("Tom Reyes", "I will send the draft by Friday."),
    ("Priya Shah", "Decision: we ship the beta on 15 November."),
    ("Dana Cole", "Can we move the budget review to Tuesday?"),
    ("Tom Reyes", "Yes, Tuesday works for me."),
    ("Priya Shah", "Great, that is everything. Thanks all."),
]
OFFSETS = [1000, 5500, 9000, 14250, 18000, 21000]
FIXTURE_FILES = {
    "vtt": FIXTURES / "meeting.vtt",
    "srt": FIXTURES / "meeting.srt",
    "text": FIXTURES / "meeting.txt",
    "meet-bot": FIXTURES / "meetbot" / "transcript.jsonl",
}


def fixture_bytes(kind: str) -> bytes:
    return FIXTURE_FILES[kind].read_bytes()


def state_bytes() -> bytes:
    return (FIXTURES / "meetbot" / "state.json").read_bytes()


class Rig:
    """The real `ArtifactStore` over memory backends, with the recording safety fake that ingest screens through."""

    def __init__(self) -> None:
        self.safety = make_safety_provider()
        self.alerts: list[dict[str, Any]] = []
        self.meta, self.blobs = MemoryMetaBackend(), MemoryBlobBackend()
        self.store = ArtifactStore(
            self.meta,
            self.blobs,
            clock=lambda: datetime.now(UTC),
            redactor=lambda text: text,
            archive_lookup=lambda scope, ref: None,
            alert_sink=self.alerts.append,
            screener=make_safety_provider(),  # the store's own verdict on the stored bytes (AR-07), apart from ingest's
        )

    def ingest(self, kind: str, data: bytes, **kwargs: Any) -> TranscriptIngest:
        base: dict[str, Any] = {
            "meeting_id": MEETING_ID,
            "scope": SCOPE,
            "run_id": RUN_ID,
            "store": self.store,
            "safety": self.safety,
            "ts": TS,
            "actor": "A_s1",
            "seq": 7,
        }
        return ingest_transcript(kind, data, **{**base, **kwargs})

    def stored_content(self, result: TranscriptIngest) -> dict[str, Any]:
        import json  # noqa: PLC0415

        return json.loads(self.store.read(SCOPE, result.artifact))


def pairs(content: dict[str, Any]) -> list[tuple[str, str]]:
    return [(u["speaker"], u["text"]) for u in content["utterances"]]


def assert_ordered_and_valid(content: dict[str, Any]) -> None:
    assert_valid_transcript(content)
    assert [u["id"] for u in content["utterances"]] == [f"u{n:04d}" for n in range(1, len(content["utterances"]) + 1)]
    offsets = [u["t_ms"] for u in content["utterances"]]
    assert offsets == sorted(offsets)
