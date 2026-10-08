"""The transcript upload route's work (FR-MTG-02-ROUTE; FR-MTG-02, FR-MTG-17, FR-MTG-01, FR-MTG-10; PE-05, PE-12, PE-22;
services/api/tests/API_FR_MTG_02_ROUTE.md). The body is the raw file and the `Content-Type` picks the path: a VTT, SRT,
text or meet-bot file is parsed by `tilo_planning.transcript_ingest`, a recording goes through the injected
`SpeechProvider` (`transcribe_recording`); both end in the one `store_transcript` step (same screening, same hint).
Effects, in order, each undone if a later one fails: the version in the artifact store (the meeting's own `Scope`),
the meeting record's `transcript` ref and `delete_transcript_after` (compare-and-set), one registered event to the
meeting's world.
Owner only, one 404. Deterministic code and the injected providers only; no clock read (`now` is handed in), no log,
and no transcript text in an answer, an error or an event. The upload bytes and any client filename are untrusted."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, Request
from pydantic import BaseModel
from tilo_memory.artifacts import ArtifactNotFound, ArtifactRefused, ArtifactStore, Scope
from tilo_people.errors import NotFound, VersionConflict
from tilo_planning.recording import RecordingLimits, RecordingRejected, media_type_allowed, transcribe_recording
from tilo_planning.transcript_ingest import MAX_INPUT_BYTES, TranscriptIngest, ingest_transcript, store_transcript
from tilo_policy.schemas import conforms
from tilo_providers.interfaces import SafetyProvider, SpeechProvider
from tilo_providers.speech import load_speech_config

from tilo_api import deps, events
from tilo_api.people_meetings import _WORLD, _mine
from tilo_api.people_quotes import GONE
from tilo_api.people_writes import Refusal, Writer, _capped_body

KEPT_DAYS = 30  # FR-MTG-10: a transcript is kept 30 days from its last upload (BQ-MTG02R-4)
_SPEECH_YAML = Path(__file__).resolve().parents[4] / "config" / "speech.yaml"
# text types by exact media type (parameters such as `; charset=utf-8` dropped); a recording is audio/* or mp4/webm
_KINDS = {
    "text/vtt": "vtt",
    "application/x-subrip": "srt",
    "text/plain": "text",
    "application/x-ndjson": "meet-bot",
    "application/jsonl": "meet-bot",
}
_OPEN_STATUSES = ("scheduled", "ended")  # not `joining` or `live` (the bot is capturing), not `minuted` (see below)
_SUMMARY = {False: "A transcript was stored.", True: "The safety screen flagged an uploaded transcript."}


class _Print(BaseModel):
    """What an `Idempotency-Key` fingerprints: the kind and the digest of the upload, never the upload."""

    kind: str
    sha256: str


@dataclass(frozen=True)
class Upload:
    kind: str  # vtt | srt | text | meet-bot | recording
    data: bytes
    media_type: str | None = None  # a recording's, already normalised
    limits: RecordingLimits | None = None  # a recording's caps from config/speech.yaml

    def fingerprint(self) -> BaseModel:
        return _Print(kind=self.kind, sha256=hashlib.sha256(self.data).hexdigest())


def _speech_limits() -> RecordingLimits:
    try:
        config = load_speech_config(_SPEECH_YAML)
    except Exception:
        raise Refusal(503, "not_configured") from None
    return RecordingLimits(config.max_bytes, config.max_duration_ms)


async def read_upload(request: Request) -> Upload:
    """415 for any other type and 413 past the cap, both before the body is read whole: the text cap is the ingest's
    4,000,000 bytes, a recording's is `max_bytes` of config/speech.yaml. The client's filename is never looked at."""
    ctype = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if ctype in _KINDS:
        return Upload(_KINDS[ctype], await _capped_body(request, MAX_INPUT_BYTES))
    try:
        media = media_type_allowed(ctype)
    except RecordingRejected:
        raise Refusal(415, "unsupported_media_type") from None
    limits = _speech_limits()
    return Upload("recording", await _capped_body(request, limits.max_bytes), media, limits)


@dataclass(frozen=True)
class TranscriptSeams:
    """The artifact store, the safety screen and the single event writer must be wired (503 before anything is
    read); the speech provider and the meeting-world maker are asked only when the upload needs them."""

    artifacts: ArtifactStore
    safety: SafetyProvider
    writer: deps.EventWriter
    speech: Callable[[], SpeechProvider]
    worlds: Callable[[], deps.MeetingWorlds]


def get_transcript_seams(
    request: Request,
    artifacts: Annotated[ArtifactStore, Depends(deps.get_artifact_store)],
    safety: Annotated[SafetyProvider, Depends(deps.get_safety)],
    writer: Annotated[deps.EventWriter, Depends(deps.get_event_writer)],
) -> TranscriptSeams:
    def lazy(seam: Callable[[], Any]) -> Callable[[], Any]:
        return lambda: request.app.dependency_overrides.get(seam, seam)()

    return TranscriptSeams(artifacts, safety, writer, lazy(deps.get_speech), lazy(deps.get_meeting_worlds))


def _ingest(up: Upload, mid: str, scope: Scope, w: Writer, seams: TranscriptSeams, parent: Any) -> TranscriptIngest:
    common: dict[str, Any] = {
        "scope": scope, "run_id": f"r_{mid[3:]}", "store": seams.artifacts, "ts": w.now, "actor": w.actor, "seq": 0,
        "parent": parent,
    }  # fmt: skip
    try:
        if up.limits is None or up.media_type is None:
            return ingest_transcript(up.kind, up.data, meeting_id=mid, safety=seams.safety, **common)
        made = transcribe_recording(
            up.data, up.media_type, meeting_id=mid, speech=seams.speech(), safety=seams.safety, limits=up.limits
        )
        return store_transcript(
            made.content, made.origin, flagged=made.safety_flagged, reason=made.safety_reason, **common
        )
    except RecordingRejected:  # also `TranscriptRejected`: the reasons hold sizes and limits, never content
        raise Refusal(422, "invalid_transcript") from None
    except ArtifactRefused:  # the store's own rules (AR-04, AR-07): a fixed message, never the content
        raise Refusal(422, "invalid_transcript") from None
    except ArtifactNotFound:  # the earlier version is gone (swept between the check and the write)
        raise Refusal(409, "transcript_expired", code="transcript_expired") from None


def _timestamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def _discard(artifacts: ArtifactStore, scope: Scope, ref: dict[str, Any]) -> None:
    """Best effort (never masks the refusal that caused it): removes the one version this request stored."""
    try:
        prefix = f"orgs/{scope.org_id}/worlds/{scope.world_id}/artifacts/{ref['artifact_id']}/versions"
        artifacts.retention().delete(f"{prefix}/{ref['version']:06d}")
    except Exception:  # noqa: BLE001, S110
        pass


def store_upload(w: Writer, seams: TranscriptSeams, meeting_id: str, up: Upload) -> dict[str, Any]:
    """The owner's upload (FR-MTG-01: the meeting was created with the attestation, which the record keeps, so there
    is no second one). The answer is ids and counts only."""
    m, version, _ = _mine(w, meeting_id, "edit", GONE)
    if m["minutes"] is not None:  # the minutes pin a transcript version; another one would leave them citing the old
        raise Refusal(409, "minutes_exist", code="minutes_exist")
    if m["status"] not in _OPEN_STATUSES or not m.get("attestation"):
        raise Refusal(409, "meeting_state", code="meeting_state")
    if m["transcript"] is not None and w.now >= (m["delete_transcript_after"] or "9"):
        raise Refusal(409, "transcript_expired", code="transcript_expired")  # wait for the sweep, then upload afresh
    world = m.get("world_id")
    if world is None:  # nothing is stored outside a world: the maker's (idempotent), written with the ref (BQ-MTG02R-2)
        world = seams.worlds().make_meeting_world(org_id=w.org, owner=m["owner"], meeting_id=m["id"])
        if not isinstance(world, str) or _WORLD.fullmatch(world) is None:
            raise ValueError("not a world id")  # never stored: the route's 503
    scope = Scope(m["org_id"], world, m["owner"])
    made = _ingest(up, meeting_id, scope, w, seams, m["transcript"])
    ref = {"artifact_id": made.artifact["artifact_id"], "version": made.artifact["version"]}
    until = _timestamp(datetime.fromisoformat(w.now) + timedelta(days=KEPT_DAYS))
    after = {
        **m,
        "world_id": world,
        "transcript": ref,
        "delete_transcript_after": until,
    }  # `decide(edit)` ran in `_mine`
    if not conforms("meeting.schema.json", after):
        _discard(seams.artifacts, scope, ref)
        raise Refusal(422, "invalid_record")
    try:
        stored = w.stores.meetings.replace(after, expected_version=version)
    except (VersionConflict, NotFound) as lost:
        _discard(seams.artifacts, scope, ref)
        if isinstance(lost, NotFound):
            raise Refusal(404, "not_found") from None
        raise Refusal(409, "version_conflict", code="version_conflict") from None
    except Exception:
        _discard(seams.artifacts, scope, ref)
        raise
    event = made.events[0]
    part = {
        "id": events.new_part_id(), "type": event["type"], "actor": w.actor, "target": event["target"],
        "summary": _SUMMARY[made.safety_flagged], "severity": event["severity"], "vis": [], "authz": None,
        "data": event["data"],
    }  # fmt: skip  # ids, hashes and counts only (PE-12): no label, title or line
    try:
        seams.writer.append(world, part)
    except Exception:
        try:  # HR-1: no ref without its event; a record another write changed since is left alone, and its version
            w.stores.meetings.replace(m, expected_version=stored.version)
            _discard(seams.artifacts, scope, ref)
        except (VersionConflict, NotFound):
            pass
        raise Refusal(503, "unavailable") from None
    return {
        "id": meeting_id, "transcript": ref, "utterances": made.origin["utterances"], "flagged": made.safety_flagged,
        "origin": made.origin["kind"], "delete_transcript_after": until,
    }  # fmt: skip
