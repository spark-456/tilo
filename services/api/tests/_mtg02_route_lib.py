"""Helpers for the FR-MTG-02-ROUTE acceptance tests (`POST /v1/meetings/{id}/transcript`, pinned in
`API_FR_MTG_02_ROUTE.md`). Built on `_ppl11a_lib.Rig` (the real app with every people seam faked) and the planning
fixtures of FR-MTG-02. Fakes only: the deterministic safety fake, `FakeSpeechProvider`, an in-memory artifact store.
No network, no paid call, no secret."""

from __future__ import annotations

import json
import pathlib
from typing import Any

from _clint1_lib import seam
from _ppl11a_lib import PRIYA, Rig
from _ppl11c_lib import MEETING_BODY

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
FIXTURES = REPO_ROOT / "packages" / "planning" / "tests" / "fixtures" / "mtg02"
CTYPE = {
    "vtt": "text/vtt",
    "srt": "application/x-subrip",
    "text": "text/plain",
    "meet-bot": "application/x-ndjson",
}
FILES = {
    "vtt": FIXTURES / "meeting.vtt",
    "srt": FIXTURES / "meeting.srt",
    "text": FIXTURES / "meeting.txt",
    "meet-bot": FIXTURES / "meetbot" / "transcript.jsonl",
}
PHRASES = ("roadmap review", "send the draft", "Priya Shah", "Tom Reyes", "budget review")  # never in an answer
RECORDING = b"ID3-fixture-recording-120s\n" + bytes(range(256)) * 16
SEGMENTS = [
    {"speaker": "Priya Shah", "start_ms": 1000, "text": "Let's start with the roadmap review."},
    {"speaker": "Tom Reyes", "start_ms": 5500, "text": "I will send the draft by Friday."},
]
NOW_PLUS_30 = "2026-11-05T10:00:00.000Z"  # NOW (2026-10-06T10:00Z) + 30 days


def fixture(kind: str) -> bytes:
    return FILES[kind].read_bytes()


def upload_rig(people_rig: Any, *, segments: list[dict[str, Any]] | None = None) -> tuple[Rig, str]:
    """A rig signed in as u_priya, who owns a freshly created, attested upload meeting (no world yet). Returns
    (rig, meeting id). The safety fake flags the injection marker; the speech fake answers `segments`."""
    from tilo_api import deps  # noqa: PLC0415
    from tilo_providers.safety import FakeSafetyProvider  # noqa: PLC0415
    from tilo_providers.speech import FakeSpeechProvider  # noqa: PLC0415

    rig = people_rig()
    rig.add_people()
    rig.as_user(PRIYA)
    rig._ids = ["art_up1", "art_up2", "art_up3"]
    rig.safety, rig.speech = FakeSafetyProvider(), FakeSpeechProvider(SEGMENTS if segments is None else segments)
    rig.app.dependency_overrides[deps.get_safety] = lambda: rig.safety
    rig.app.dependency_overrides[seam(deps, "get_speech")] = lambda: rig.speech
    created = rig.post("/v1/meetings", MEETING_BODY)
    assert created.status_code == 201, created.text[:200]
    return rig, created.json()["id"]


def path(meeting_id: str) -> str:
    return f"/v1/meetings/{meeting_id}/transcript"


def up(rig: Rig, meeting_id: str, body: bytes, ctype: str, **headers: str) -> Any:
    return rig.client.post(path(meeting_id), content=body, headers={"content-type": ctype, **headers})


def stored_transcript(rig: Rig, meeting_id: str) -> dict[str, Any]:
    """The transcript version the meeting record points at, read back through the store in its own scope."""
    from tilo_memory.artifacts import Scope  # noqa: PLC0415

    m = rig.stored("meetings", meeting_id)
    assert m is not None and m["transcript"] is not None
    scope = Scope(m["org_id"], m["world_id"], m["owner"])
    return json.loads(rig.artifacts.read(scope, m["transcript"]))  # type: ignore[no-any-return]


def stored_record(rig: Rig, meeting_id: str) -> dict[str, Any]:
    from tilo_memory.artifacts import Scope  # noqa: PLC0415

    m = rig.stored("meetings", meeting_id)
    assert m is not None and m["transcript"] is not None
    return dict(rig.artifacts.head(Scope(m["org_id"], m["world_id"], m["owner"]), m["transcript"]).record)  # type: ignore[union-attr]
