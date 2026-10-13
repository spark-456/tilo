"""Import analysed minutes for owner review (FR-MTG-03/04/10), without confirming or sending anything."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from pydantic import ValidationError
from tilo_contracts import Minutes, Transcript
from tilo_memory.artifacts import ArtifactError, ArtifactNotFound, ArtifactStore, NewVersion, Origin, Scope
from tilo_people.errors import NotFound, VersionConflict
from tilo_policy.schemas import conforms
from tilo_providers.interfaces import SafetyProvider
from tilo_providers.router import Router

from tilo_api import deps
from tilo_api import events as event_parts
from tilo_api.meeting_analysis import analyze_minutes
from tilo_api.people_meetings import _clean, _mine
from tilo_api.people_quotes import GONE
from tilo_api.people_writes import Refusal, Writer, _purge


def analyze_and_publish_minutes(
    w: Writer,
    store: deps.Store,
    artifacts: ArtifactStore,
    meeting_id: str,
    *,
    router: Router,
    meeting_at: str,
    budget: float,
    safety: SafetyProvider,
    events: deps.EventWriter,
) -> dict[str, Any]:
    """Internal service seam, never a client body. Router/budget/mode and actual meeting start are trusted inputs.

    Authorise before reading content or spending. ArtifactStore reads the exact immutable, hash-checked version.
    Publication rechecks access/retention/world and requires the same meeting version seen before generation.
    No confirmation, proposed item, recipient, approval card or outbox entry is created here.
    """
    meeting, version, _ = _mine(w, meeting_id, "read_full", GONE)
    if meeting["status"] != "ended" or meeting["minutes"] is not None:
        raise Refusal(409, "not_publishable")
    world_id, ref, until = meeting.get("world_id"), meeting["transcript"], meeting["delete_transcript_after"]
    if world_id is None or ref is None or until is None or w.now >= until:
        raise Refusal(409, "transcript_unavailable")
    world = store.load_world(world_id, settle=False)
    if world is None or world.owner != w.actor:
        raise Refusal(404, "not_found")
    scope = Scope(w.org, world_id, w.actor)
    try:
        head = artifacts.head(scope, ref)
        if head is None or head.doc["screening"] != "clean":
            raise Refusal(409, "transcript_unavailable")
        transcript = json.loads(artifacts.read(scope, ref))
        if not isinstance(transcript, dict) or transcript.get("meeting_id") != meeting_id:
            raise Refusal(409, "transcript_unavailable")
    except (ArtifactError, ValueError):
        raise Refusal(409, "transcript_unavailable") from None
    try:
        # Directory is server-owned; match_name applies directory visibility. None of its records go to the model.
        doc = analyze_minutes(
            router,
            transcript,
            ref,
            directory=w.org_directory(),
            viewer=w.actor,
            meeting_at=meeting_at,
            now=w.now,
            budget=budget,
            safety=safety,
            agenda=meeting["agenda"],
        )
    except ValueError:
        raise Refusal(502, "analysis_failed") from None
    return publish_minutes(w, store, artifacts, meeting_id, doc, events=events, expected_version=version)


def publish_minutes(
    w: Writer,
    store: deps.Store,
    artifacts: ArtifactStore,
    meeting_id: str,
    minutes: dict[str, Any],
    *,
    events: deps.EventWriter,
    expected_version: int | None = None,
) -> dict[str, Any]:
    """Internal offline import seam. Caller supplies analysed data, never an authorisation or confirmation stamp.

    Analyst generation, semantic verification and identity/date resolution precede this seam. No public route
    accepts this input; no work item, card or outbox entry is produced here.
    """
    meeting, version, _ = _mine(w, meeting_id, "read_full", GONE)
    if expected_version is not None and version != expected_version:
        raise Refusal(409, "version_conflict")
    if meeting["status"] != "ended" or meeting["minutes"] is not None:
        raise Refusal(409, "not_publishable")
    world_id, transcript_ref = meeting.get("world_id"), meeting["transcript"]
    until = meeting["delete_transcript_after"]
    if world_id is None or transcript_ref is None or until is None or w.now >= until:
        raise Refusal(409, "transcript_unavailable")
    world = store.load_world(world_id, settle=False)
    if world is None or world.owner != w.actor:
        raise Refusal(404, "not_found")
    scope = Scope(w.org, world_id, w.actor)
    try:
        transcript = Transcript.model_validate_json(artifacts.read(scope, transcript_ref))
        head = artifacts.head(scope, transcript_ref)
        doc = _clean(minutes, w.redact)
        Minutes.model_validate(doc)
    except ArtifactNotFound:
        raise Refusal(409, "transcript_unavailable") from None
    except (ValidationError, ValueError):
        raise Refusal(422, "invalid_minutes") from None
    if head is None or transcript.meeting_id != meeting_id:
        raise Refusal(409, "transcript_unavailable")
    if doc["meeting_id"] != meeting_id or doc["transcript"] != transcript_ref:
        raise Refusal(422, "invalid_minutes")
    ids = {utterance.id for utterance in transcript.utterances}
    for group in ("summary", "decisions", "action_items", "agenda"):
        for row in doc[group]:
            if row.get("state") != "unverified" and not set(row["evidence"]) <= ids:
                raise Refusal(422, "invalid_evidence")
    if any(row["work_item_id"] is not None for row in doc["action_items"]):
        raise Refusal(422, "linked_items_not_allowed")
    doc["flagged"] = doc["flagged"] or head.doc["screening"] != "clean"
    if not conforms("minutes.schema.json", doc):
        raise Refusal(422, "invalid_minutes")
    made = artifacts.put(
        scope,
        NewVersion(
            "application/json",
            json.dumps(doc).encode(),
            world.run_id,
            Origin(kind="upload"),
            screening_hint="flagged" if doc["flagged"] else None,
        ),
    )
    committed = None
    try:
        stored = json.loads(artifacts.read(scope, made.ref))
        Minutes.model_validate(stored)
        if stored != doc:
            raise Refusal(422, "minutes_changed")
        # A flag found by the minutes screen must be present in the content, not only its artifact metadata.
        if made.doc["screening"] != "clean" and not stored["flagged"]:
            raise Refusal(422, "minutes_flagged")
        expires = datetime.fromisoformat(w.now.replace("Z", "+00:00")) + timedelta(days=90)
        after = {
            **meeting,
            "status": "minuted",
            "minutes": made.ref,
            "minutes_confirmed_by": None,
            "delete_minutes_after": expires.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        }
        if not conforms("meeting.schema.json", after):
            raise Refusal(422, "invalid_record")
        committed = w.stores.meetings.replace(after, expected_version=version)
        claims = stored["decisions"] + stored["action_items"]
        part: dict[str, Any] = {
            "id": event_parts.new_part_id(),
            "type": "meeting.minuted",
            "actor": w.actor,
            "target": w.actor,
            "severity": "needs_you",
            "summary": "Meeting minutes are ready for review.",
            "vis": [],
            "authz": None,
            "data": {
                "meeting_id": meeting_id,
                "minutes": made.ref,
                "decisions": len(stored["decisions"]),
                "action_items": len(stored["action_items"]),
                "unverified": sum(row["state"] == "unverified" for row in claims),
                "flagged": stored["flagged"],
            },
        }
        # Same part id on bounded retries: the single writer deduplicates lost acknowledgements.
        for attempt in range(3):
            try:
                events.append(world_id, part)
                return after
            except Exception:
                if attempt == 2:
                    raise Refusal(503, "unavailable") from None
    except BaseException as exc:
        purge = committed is None
        if committed is not None:
            try:
                w.stores.meetings.replace(meeting, expected_version=committed.version)
                purge = True
            except (VersionConflict, NotFound):
                pass  # a concurrent write may still refer to these minutes; never delete its artifact
        if purge:
            _purge(artifacts, scope, made.artifact_id)
        if isinstance(exc, VersionConflict):
            raise Refusal(409, "version_conflict") from None
        raise
    raise Refusal(503, "unavailable")
